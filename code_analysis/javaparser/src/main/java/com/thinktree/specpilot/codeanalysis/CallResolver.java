package com.thinktree.specpilot.codeanalysis;

import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import com.github.javaparser.resolution.declarations.ResolvedReferenceTypeDeclaration;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.javaparsermodel.declarations.JavaParserMethodDeclaration;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import com.github.javaparser.utils.SourceRoot;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.TimeUnit;

/**
 * code_analysis의 Java 호출 해석기.
 *
 * 메서드 호출마다 JavaParser + Symbol Solver로 "어느 클래스의 어느 선언으로 가는지"를 풀어 JSON으로 낸다.
 * 사실(fact) 문장은 만들지 않는다. 문장, 템플릿·JS 분석, 화면 나누기, ③ 줄 목록과의 대조는 Python(code_analysis)이 한다.
 *
 * 입력 폴더(--src)는 Python이 ③(backend load_codebase)의 파일 목록과 줄 그대로 다시 써 둔 사본이다.
 * 그래서 이 도구가 내는 파일 경로와 줄 번호는 ③의 "=== 경로 ===", "줄번호|"와 같다.
 *
 * 실행: java -jar specpilot-javaparser.jar --src DIR --out FILE [--classpath FILE] [--gradle-root DIR]
 */
public class CallResolver {

    private static final String VERSION = "0.1.0";

    /** 호출 하나의 결과 */
    private static final class CallOut {
        String file;
        int line;
        int col;
        String name;
        int index;                 // 같은 줄에서 같은 이름 호출 중 몇 번째인지 (0부터, 열 순서)
        String receiver;
        boolean resolved;
        String declaringType;
        String declaringQualified;
        String declaringKind;       // class | interface | enum | record | other
        String signature;
        int params = -1;
        String declFile;            // 선언이 이 소스 안에 있으면 그 파일
        int declLine;               // 선언의 메서드 이름 줄
        final List<String[]> impls = new ArrayList<>();   // {파일, 줄, 클래스}
        String error;
    }

    public static void main(String[] args) throws Exception {
        Map<String, String> opts = parseArgs(args);
        if (!opts.containsKey("src") || !opts.containsKey("out")) {
            System.err.println("사용법: java -jar specpilot-javaparser.jar --src DIR --out FILE [--classpath FILE] [--gradle-root DIR]");
            System.exit(2);
        }
        Path src = Paths.get(opts.get("src")).toAbsolutePath().normalize();
        Path out = Paths.get(opts.get("out")).toAbsolutePath().normalize();
        long started = System.currentTimeMillis();

        // ---- 타입 해석기: JDK + (있으면) 라이브러리 jar + 소스 루트들
        CombinedTypeSolver typeSolver = new CombinedTypeSolver();
        typeSolver.add(new ReflectionTypeSolver(true));
        List<String> notes = new ArrayList<>();
        Path classpathFile = opts.containsKey("classpath") ? Paths.get(opts.get("classpath")) : null;
        if (classpathFile == null && opts.containsKey("gradle-root")) {
            try {
                classpathFile = Classpath.fromGradle(Paths.get(opts.get("gradle-root")));
                notes.add("Gradle에서 classpath를 읽음");
            } catch (Exception e) {
                notes.add("Gradle classpath 추출 실패 (라이브러리 타입 없이 진행): " + e.getMessage());
            }
        }
        int jars = classpathFile != null ? Classpath.addJars(typeSolver, classpathFile, notes) : 0;

        ParserConfiguration config = new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17)
                .setCharacterEncoding(StandardCharsets.UTF_8)
                .setSymbolResolver(new JavaSymbolSolver(typeSolver));
        SourceRoot root = new SourceRoot(src, config);
        List<ParseResult<CompilationUnit>> results = root.tryToParse("");

        List<CompilationUnit> units = new ArrayList<>();
        List<String> parseErrors = new ArrayList<>();
        Set<Path> sourceRoots = new LinkedHashSet<>();
        for (ParseResult<CompilationUnit> r : results) {
            if (r.getResult().isPresent()) {
                CompilationUnit cu = r.getResult().get();
                units.add(cu);
                cu.getStorage().ifPresent(s -> sourceRoots.add(sourceRootOf(s)));
            }
            if (!r.isSuccessful()) {
                parseErrors.add(String.valueOf(r.getProblems()));
            }
        }
        // 소스 루트(패키지가 시작하는 폴더)를 찾은 뒤에 소스 타입 해석기를 붙인다. 해석은 아래에서 처음 일어난다.
        for (Path sr : sourceRoots) {
            typeSolver.add(new JavaParserTypeSolver(sr));
        }

        // ---- 인터페이스 → 구현 클래스 (단순 이름 기준)
        Map<String, List<ClassOrInterfaceDeclaration>> implsByIface = new LinkedHashMap<>();
        for (CompilationUnit cu : units) {
            for (ClassOrInterfaceDeclaration c : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                if (c.isInterface()) {
                    continue;
                }
                for (ClassOrInterfaceType t : c.getImplementedTypes()) {
                    implsByIface.computeIfAbsent(t.getNameAsString(), k -> new ArrayList<>()).add(c);
                }
            }
        }

        // ---- 호출마다 풀기
        List<CallOut> calls = new ArrayList<>();
        int resolved = 0, toSource = 0;
        Map<String, Integer> errors = new TreeMap<>();
        for (CompilationUnit cu : units) {
            String file = rel(src, cu);
            List<MethodCallExpr> found = cu.findAll(MethodCallExpr.class);
            List<CallOut> inFile = new ArrayList<>();
            for (MethodCallExpr mce : found) {
                CallOut c = new CallOut();
                c.file = file;
                c.line = mce.getName().getBegin().map(p -> p.line).orElse(-1);
                c.col = mce.getName().getBegin().map(p -> p.column).orElse(-1);
                c.name = mce.getNameAsString();
                c.receiver = mce.getScope().map(Node::toString).orElse(null);
                try {
                    ResolvedMethodDeclaration r = mce.resolve();
                    ResolvedReferenceTypeDeclaration d = r.declaringType();
                    c.resolved = true;
                    c.declaringType = d.getName();
                    c.declaringQualified = d.getQualifiedName();
                    c.declaringKind = d.isInterface() ? "interface" : d.isEnum() ? "enum" : d.isClass() ? "class" : "other";
                    c.signature = r.getQualifiedSignature();
                    c.params = r.getNumberOfParams();
                    if (r instanceof JavaParserMethodDeclaration) {
                        MethodDeclaration md = ((JavaParserMethodDeclaration) r).getWrappedNode();
                        c.declFile = md.findCompilationUnit().map(u -> rel(src, u)).orElse(null);
                        c.declLine = md.getName().getBegin().map(p -> p.line).orElse(-1);
                        toSource++;
                        if (d.isInterface()) {
                            for (ClassOrInterfaceDeclaration impl : implsByIface.getOrDefault(d.getName(), List.of())) {
                                for (MethodDeclaration im : impl.getMethodsByName(c.name)) {
                                    if (im.getParameters().size() == c.params) {
                                        String implFile = im.findCompilationUnit().map(u -> rel(src, u)).orElse(null);
                                        int implLine = im.getName().getBegin().map(p -> p.line).orElse(-1);
                                        c.impls.add(new String[]{implFile, String.valueOf(implLine), impl.getNameAsString()});
                                    }
                                }
                            }
                        }
                    }
                    resolved++;
                } catch (Throwable t) {               // UnsolvedSymbolException, UnsupportedOperationException, StackOverflowError …
                    c.resolved = false;
                    c.error = t.getClass().getSimpleName();
                    errors.merge(c.error, 1, Integer::sum);
                }
                inFile.add(c);
            }
            // 같은 줄·같은 이름 호출의 순번 (Python의 tree-sitter 결과와 맞출 때 쓴다. 열 번호는 바이트/글자 차이가 있어 쓰지 않음)
            Map<String, List<CallOut>> groups = new LinkedHashMap<>();
            for (CallOut c : inFile) {
                groups.computeIfAbsent(c.line + "|" + c.name, k -> new ArrayList<>()).add(c);
            }
            for (List<CallOut> g : groups.values()) {
                g.sort(Comparator.comparingInt(x -> x.col));
                for (int i = 0; i < g.size(); i++) {
                    g.get(i).index = i;
                }
            }
            calls.addAll(inFile);
        }

        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"tool\": ").append(q("specpilot-javaparser " + VERSION)).append(",\n");
        sb.append("  \"src\": ").append(q(src.toString())).append(",\n");
        sb.append("  \"files\": ").append(units.size()).append(",\n");
        sb.append("  \"library_jars\": ").append(jars).append(",\n");
        sb.append("  \"source_roots\": [");
        List<String> srs = new ArrayList<>();
        for (Path sr : sourceRoots) {
            srs.add(q(src.relativize(sr).toString().replace('\\', '/')));
        }
        sb.append(String.join(", ", srs)).append("],\n");
        sb.append("  \"notes\": [").append(joinQ(notes)).append("],\n");
        sb.append("  \"parse_errors\": [").append(joinQ(parseErrors)).append("],\n");
        sb.append("  \"stats\": {\"calls\": ").append(calls.size()).append(", \"resolved\": ").append(resolved)
                .append(", \"resolved_to_source\": ").append(toSource).append(", \"errors\": {");
        List<String> es = new ArrayList<>();
        for (Map.Entry<String, Integer> e : errors.entrySet()) {
            es.add(q(e.getKey()) + ": " + e.getValue());
        }
        sb.append(String.join(", ", es)).append("}, \"millis\": ").append(System.currentTimeMillis() - started).append("},\n");
        sb.append("  \"calls\": [\n");
        for (int i = 0; i < calls.size(); i++) {
            sb.append("    ").append(callJson(calls.get(i))).append(i < calls.size() - 1 ? ",\n" : "\n");
        }
        sb.append("  ]\n}\n");
        Files.createDirectories(out.getParent());
        Files.writeString(out, sb.toString(), StandardCharsets.UTF_8);
        System.out.println("호출 " + calls.size() + "개 중 " + resolved + "개 해석 (소스 안의 선언 " + toSource
                + "개), 라이브러리 jar " + jars + "개 → " + out);
    }

    private static String callJson(CallOut c) {
        StringBuilder sb = new StringBuilder("{");
        sb.append("\"file\": ").append(q(c.file))
                .append(", \"line\": ").append(c.line)
                .append(", \"col\": ").append(c.col)
                .append(", \"name\": ").append(q(c.name))
                .append(", \"index\": ").append(c.index)
                .append(", \"receiver\": ").append(q(c.receiver))
                .append(", \"resolved\": ").append(c.resolved);
        if (c.resolved) {
            sb.append(", \"declaring_type\": ").append(q(c.declaringType))
                    .append(", \"declaring_qualified\": ").append(q(c.declaringQualified))
                    .append(", \"declaring_kind\": ").append(q(c.declaringKind))
                    .append(", \"signature\": ").append(q(c.signature))
                    .append(", \"params\": ").append(c.params)
                    .append(", \"decl_file\": ").append(q(c.declFile))
                    .append(", \"decl_line\": ").append(c.declFile == null ? "null" : String.valueOf(c.declLine));
            List<String> im = new ArrayList<>();
            for (String[] x : c.impls) {
                im.add("{\"file\": " + q(x[0]) + ", \"line\": " + x[1] + ", \"type\": " + q(x[2]) + "}");
            }
            sb.append(", \"impls\": [").append(String.join(", ", im)).append("]");
        } else {
            sb.append(", \"error\": ").append(q(c.error));
        }
        return sb.append("}").toString();
    }

    /** 패키지 선언과 폴더가 맞지 않으면 getSourceRoot()가 예외를 던지므로, 그때는 파일이 있는 폴더를 쓴다. */
    private static Path sourceRootOf(CompilationUnit.Storage s) {
        try {
            return s.getSourceRoot();
        } catch (RuntimeException e) {
            return s.getPath().getParent();
        }
    }

    private static String rel(Path src, CompilationUnit cu) {
        return cu.getStorage().map(s -> src.relativize(s.getPath().toAbsolutePath().normalize()).toString().replace('\\', '/'))
                .orElse("?");
    }

    private static String joinQ(List<String> xs) {
        List<String> out = new ArrayList<>();
        for (String x : xs) {
            out.add(q(x));
        }
        return String.join(", ", out);
    }

    static String q(String s) {
        if (s == null) {
            return "null";
        }
        StringBuilder sb = new StringBuilder("\"");
        for (char ch : s.toCharArray()) {
            switch (ch) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (ch < 0x20) {
                        sb.append(String.format("\\u%04x", (int) ch));
                    } else {
                        sb.append(ch);
                    }
            }
        }
        return sb.append('"').toString();
    }

    private static Map<String, String> parseArgs(String[] args) {
        Map<String, String> m = new LinkedHashMap<>();
        for (int i = 0; i < args.length; i++) {
            if (args[i].startsWith("--") && i + 1 < args.length) {
                m.put(args[i].substring(2), args[i + 1]);
                i++;
            }
        }
        return m;
    }

    /** 라이브러리 classpath: 파일에서 읽거나 Gradle로 뽑는다 (2주차 분석기 v6/v7과 같은 방식). */
    static final class Classpath {
        private static final String INIT_SCRIPT =
                "allprojects {\n"
                + "    tasks.register(\"printAnalyzerClasspath\") {\n"
                + "        doLast {\n"
                + "            if (project.plugins.hasPlugin(\"java\")) {\n"
                + "                def jars = new LinkedHashSet<File>()\n"
                + "                jars.addAll(project.sourceSets.main.compileClasspath.files)\n"
                + "                jars.addAll(project.sourceSets.main.runtimeClasspath.files)\n"
                + "                println(jars.collect { it.absolutePath }.join(System.lineSeparator()))\n"
                + "            }\n"
                + "        }\n"
                + "    }\n"
                + "}\n";

        static Path fromGradle(Path start) throws IOException, InterruptedException {
            Path dir = start.toAbsolutePath().normalize();
            Path projectRoot = null;
            for (int i = 0; i < 10 && dir != null; i++) {
                boolean build = Files.exists(dir.resolve("build.gradle")) || Files.exists(dir.resolve("build.gradle.kts"));
                boolean wrapper = Files.exists(dir.resolve("gradlew")) || Files.exists(dir.resolve("gradlew.bat"));
                if (build && wrapper) {
                    projectRoot = dir;
                    break;
                }
                dir = dir.getParent();
            }
            if (projectRoot == null) {
                throw new IOException("gradlew와 build.gradle이 있는 폴더를 찾지 못함: " + start);
            }
            boolean windows = System.getProperty("os.name").toLowerCase().contains("win");
            Path gradlew = projectRoot.resolve(windows ? "gradlew.bat" : "gradlew");
            Path init = Files.createTempFile("specpilot-cp", ".gradle");
            Files.writeString(init, INIT_SCRIPT, StandardCharsets.UTF_8);
            Path outFile = Files.createTempFile("specpilot-cp", ".txt");
            ProcessBuilder pb = new ProcessBuilder(gradlew.toString(), "-I", init.toString(), "-q", "printAnalyzerClasspath");
            pb.directory(projectRoot.toFile());
            pb.redirectOutput(outFile.toFile());
            pb.redirectError(ProcessBuilder.Redirect.INHERIT);
            Process p = pb.start();
            if (!p.waitFor(5, TimeUnit.MINUTES)) {
                p.destroyForcibly();
                throw new IOException("Gradle이 5분 안에 끝나지 않음");
            }
            if (p.exitValue() != 0) {
                throw new IOException("Gradle 종료 코드 " + p.exitValue());
            }
            return outFile;
        }

        static int addJars(CombinedTypeSolver ts, Path file, List<String> notes) throws IOException {
            if (!Files.exists(file)) {
                notes.add("classpath 파일이 없음: " + file);
                return 0;
            }
            byte[] bytes = Files.readAllBytes(file);
            String text;
            if (bytes.length >= 2 && (bytes[0] & 0xFF) == 0xFF && (bytes[1] & 0xFF) == 0xFE) {
                text = new String(bytes, 2, bytes.length - 2, StandardCharsets.UTF_16LE);     // PowerShell 리다이렉션
            } else {
                text = new String(bytes, StandardCharsets.UTF_8);
                if (text.startsWith("\uFEFF")) {
                    text = text.substring(1);
                }
            }
            int n = 0;
            for (String line : text.split("\\R")) {
                String s = line.strip();
                if (s.isEmpty() || !s.endsWith(".jar") || !Files.isRegularFile(Paths.get(s))) {
                    continue;
                }
                try {
                    ts.add(new JarTypeSolver(s));
                    n++;
                } catch (IOException e) {
                    notes.add("jar를 읽지 못함 (건너뜀): " + s);
                }
            }
            return n;
        }
    }
}
