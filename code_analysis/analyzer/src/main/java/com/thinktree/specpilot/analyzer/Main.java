package com.thinktree.specpilot.analyzer;

import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
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
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

/**
 * 백엔드(.java + Thymeleaf) 콜그래프·바인딩 분석 (JavaParser + Symbol Solver + Jsoup).
 *
 *  - 입력은 code_analysis(Python)가 ③의 파일 목록과 줄 그대로 다시 써 둔 폴더(--src). 경로는 그 폴더 기준 상대 경로라서
 *    ③(backend load_codebase)의 경로·줄 번호와 같다).
 *  - delombok을 하지 않는다. delombok한 코드를 파싱하면 줄 번호가 원본과 달라지기 때문이다.
 *    Lombok이 만든 getter 호출은 못 풀지만, 사실에 쓰는 서비스·저장소 호출은 필드 타입으로 풀린다.
 *  - 템플릿을 소스 폴더 안의 templates/ 에서 찾는다.
 *  - 바인딩을 분기별로 본다: "예외 시 errorMessage를 넘기고 같은 화면을 반환"처럼 어느 반환에 어느 값이 가는지.
 *  - 컨트롤러 경로, 보안 설정, 검증 애노테이션, 예외 문구, 템플릿 구조를 같이 낸다.
 *  - 사실 문장은 만들지 않는다. code_analysis(Python)가 이 JSON과 JS 분석 결과로 code_facts.json을 만든다.
 *
 * 실행: java -jar specpilot-analyzer-0.8.0.jar --src DIR --out FILE [--classpath FILE] [--gradle-root DIR]
 */
public class Main {

    static final String VERSION = "0.8.1";

    public static void main(String[] args) throws Exception {
        Map<String, String> opts = parseArgs(args);
        if (!opts.containsKey("src") || !opts.containsKey("out")) {
            System.err.println("usage: java -jar specpilot-analyzer-" + VERSION + ".jar --src DIR --out FILE [--classpath FILE] [--gradle-root DIR]");
            System.exit(2);
        }
        long started = System.currentTimeMillis();
        Path src = Paths.get(opts.get("src")).toAbsolutePath().normalize();
        Path out = Paths.get(opts.get("out")).toAbsolutePath().normalize();
        List<String> notes = new ArrayList<>();

        // ---- 타입 해석기: JDK + (있으면) 라이브러리 jar + 소스 루트들
        CombinedTypeSolver typeSolver = new CombinedTypeSolver();
        typeSolver.add(new ReflectionTypeSolver(true));
        Path classpathFile = opts.containsKey("classpath") ? Paths.get(opts.get("classpath")) : null;
        if (classpathFile == null && opts.containsKey("gradle-root")) {
            try {
                classpathFile = Classpath.fromGradle(Paths.get(opts.get("gradle-root")));
                notes.add("Gradle에서 라이브러리 classpath를 읽음");
            } catch (Exception e) {
                notes.add("Gradle classpath 추출 실패, 라이브러리 타입 없이 진행: " + e.getMessage());
            }
        }
        int jars = classpathFile != null ? Classpath.addJars(typeSolver, classpathFile, notes) : 0;
        if (jars == 0) {
            notes.add("라이브러리 jar 없이 해석함: Spring·JPA에서 상속받은 메서드는 unresolved로 나올 수 있음");
        }

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
            r.getResult().ifPresent(cu -> {
                units.add(cu);
                cu.getStorage().ifPresent(s -> sourceRoots.add(sourceRootOf(s)));
            });
            if (!r.isSuccessful()) {
                parseErrors.add(String.valueOf(r.getProblems()));
            }
        }
        for (Path sr : sourceRoots) {            // 패키지가 시작하는 폴더마다 소스 타입 해석기를 붙인다 (해석은 아래에서 처음 일어남)
            typeSolver.add(new JavaParserTypeSolver(sr));
        }

        // ---- 템플릿
        Map<String, Templates.Template> templates = new LinkedHashMap<>();
        try (Stream<Path> walk = Files.walk(src)) {
            for (Path p : walk.filter(Files::isRegularFile).sorted().toList()) {
                String rel = src.relativize(p).toString().replace('\\', '/');
                if (Templates.isTemplate(rel)) {
                    try {
                        Templates.Template t = Templates.parse(p, rel);
                        templates.putIfAbsent(t.view, t);
                    } catch (IOException e) {
                        parseErrors.add("템플릿을 읽지 못함: " + rel);
                    }
                }
            }
        }

        Backend backend = new Backend(src, units, templates);
        List<Map<String, Object>> routes = backend.routes();
        Map<String, Object> json = Json.obj();
        json.put("tool", "specpilot-analyzer " + VERSION);
        json.put("src", src.toString());
        json.put("java_files", units.size());
        json.put("templates_found", templates.size());
        json.put("library_jars", jars);
        List<String> roots = new ArrayList<>();
        sourceRoots.forEach(sr -> roots.add(src.relativize(sr).toString().replace('\\', '/')));
        json.put("source_roots", roots);
        json.put("notes", notes);
        json.put("parse_errors", parseErrors);
        json.put("classes", backend.classes());
        List<Map<String, Object>> calls = backend.calls();
        json.put("call_stats", backend.callStats);
        json.put("calls", calls);
        json.put("routes", routes);
        json.put("bindings", backend.bindings(routes));
        json.put("security", backend.security());
        List<Map<String, Object>> tl = new ArrayList<>();
        templates.values().forEach(t -> tl.add(t.toJson()));
        json.put("templates", tl);
        json.put("millis", System.currentTimeMillis() - started);

        Files.createDirectories(out.getParent());
        Files.writeString(out, Json.write(json), StandardCharsets.UTF_8);
        // 콘솔은 영문으로 (Windows 코드페이지에서 한글이 깨지지 않게). 자세한 내용은 JSON에 있다.
        System.out.println("java=" + units.size() + " templates=" + templates.size() + " calls=" + calls.size()
                + " " + backend.callStats + " library_jars=" + jars + " -> " + out);
    }

    /** 패키지 선언과 폴더가 맞지 않으면 getSourceRoot()가 예외를 던지므로, 그때는 파일이 있는 폴더를 쓴다. */
    private static Path sourceRootOf(CompilationUnit.Storage s) {
        try {
            return s.getSourceRoot();
        } catch (RuntimeException e) {
            return s.getPath().getParent();
        }
    }

    private static Map<String, String> parseArgs(String[] args) {
        Map<String, String> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < args.length; i += 2) {
            if (args[i].startsWith("--")) {
                m.put(args[i].substring(2), args[i + 1]);
            }
        }
        return m;
    }

    /** 라이브러리 classpath: 파일에서 읽거나 Gradle로 뽑는다 (v6/v7과 같은 방식). */
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
