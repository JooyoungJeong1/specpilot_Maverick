package com.thinktree.specpilot.analyzer;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.ArrayInitializerExpr;
import com.github.javaparser.ast.expr.BinaryExpr;
import com.github.javaparser.ast.expr.EnclosedExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.LambdaExpr;
import com.github.javaparser.ast.expr.MemberValuePair;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NormalAnnotationExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.SingleMemberAnnotationExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.expr.TextBlockLiteralExpr;
import com.github.javaparser.ast.expr.ThisExpr;
import com.github.javaparser.ast.nodeTypes.NodeWithAnnotations;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.ThrowStmt;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import com.github.javaparser.resolution.declarations.ResolvedReferenceTypeDeclaration;
import com.github.javaparser.resolution.types.ResolvedReferenceType;
import com.github.javaparser.resolution.types.ResolvedType;
import com.github.javaparser.symbolsolver.javaparsermodel.declarations.JavaParserMethodDeclaration;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;

/**
 * 백엔드(.java) 분석: 클래스·메서드 구조, 콜그래프(Symbol Solver로 호출 대상 해석), 컨트롤러 경로,
 * 보안 설정, Controller → 템플릿 바인딩. 2주차 분석기(v7)의 collectCalls / collectBindings를 이어받아 늘렸다.
 * 사실 문장은 만들지 않는다 (Python이 이 JSON으로 만든다).
 */
@SuppressWarnings({"rawtypes", "unchecked"})
final class Backend {

    static final Map<String, String> MAPPINGS = Map.of("GetMapping", "GET", "PostMapping", "POST", "PutMapping", "PUT",
            "DeleteMapping", "DELETE", "PatchMapping", "PATCH", "RequestMapping", "");
    static final Set<String> FRAMEWORK_PARAM_TYPES = Set.of("Model", "ModelMap", "BindingResult", "Errors",
            "RedirectAttributes", "Authentication", "Principal", "HttpServletRequest", "HttpServletResponse", "HttpSession",
            "MultipartFile", "String", "Long", "Integer", "int", "long", "boolean", "Boolean", "Locale", "SessionStatus",
            "UserDetails", "Pageable", "UriComponentsBuilder");
    static final Set<String> SECURITY_MATCHERS = Set.of("requestMatchers", "antMatchers", "mvcMatchers", "regexMatchers", "anyRequest");
    static final Set<String> SECURITY_CALLS = Set.of("authorizeHttpRequests", "authorizeRequests", "formLogin", "loginPage",
            "loginProcessingUrl", "usernameParameter", "passwordParameter", "defaultSuccessUrl", "successForwardUrl",
            "failureUrl", "failureForwardUrl", "logout", "logoutUrl", "logoutSuccessUrl", "invalidateHttpSession",
            "deleteCookies", "ignoringRequestMatchers", "oauth2Login", "accessDeniedPage", "accessDeniedHandler",
            "exceptionHandling", "sessionManagement", "rememberMe", "httpBasic");

    private final Path src;
    private final List<CompilationUnit> units;
    private final Map<String, Templates.Template> templatesByView;
    private final Map<String, List<ClassOrInterfaceDeclaration>> implsByIface = new LinkedHashMap<>();
    final Map<String, Integer> callStats = new TreeMap<>();

    Backend(Path src, List<CompilationUnit> units, Map<String, Templates.Template> templatesByView) {
        this.src = src;
        this.units = units;
        this.templatesByView = templatesByView;
        for (CompilationUnit cu : units) {
            for (ClassOrInterfaceDeclaration c : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                if (!c.isInterface()) {
                    for (ClassOrInterfaceType t : c.getImplementedTypes()) {
                        implsByIface.computeIfAbsent(t.getNameAsString(), k -> new ArrayList<>()).add(c);
                    }
                }
            }
        }
    }

    // =================================================================== 클래스·메서드 구조

    List<Map<String, Object>> classes() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (CompilationUnit cu : units) {
            String file = rel(cu);
            for (TypeDeclaration<?> td : cu.findAll(TypeDeclaration.class)) {
                Map<String, Object> c = Json.obj();
                c.put("name", td.getNameAsString());
                c.put("qualified", td.getFullyQualifiedName().orElse(td.getNameAsString()));
                c.put("kind", td.isClassOrInterfaceDeclaration() && td.asClassOrInterfaceDeclaration().isInterface() ? "interface"
                        : td.isEnumDeclaration() ? "enum" : td.isRecordDeclaration() ? "record" : "class");
                c.put("file", file);
                c.put("line", line(td.getName()));
                c.put("annotations", annotations(td));
                List<String> ext = new ArrayList<>();
                List<String> impl = new ArrayList<>();
                if (td.isClassOrInterfaceDeclaration()) {
                    ClassOrInterfaceDeclaration cid = td.asClassOrInterfaceDeclaration();
                    cid.getExtendedTypes().forEach(t -> ext.add(t.getNameAsString()));
                    cid.getImplementedTypes().forEach(t -> impl.add(t.getNameAsString()));
                }
                c.put("extends", ext);
                c.put("implements", impl);
                List<Map<String, Object>> fields = new ArrayList<>();
                for (FieldDeclaration fd : td.getFields()) {
                    for (VariableDeclarator v : fd.getVariables()) {
                        Map<String, Object> f = Json.obj();
                        f.put("name", v.getNameAsString());
                        f.put("type", simpleType(v.getType().asString()));
                        f.put("line", line(v.getName()));
                        f.put("annotations", annotations(fd));
                        fields.add(f);
                    }
                }
                c.put("fields", fields);
                List<Map<String, Object>> methods = new ArrayList<>();
                for (MethodDeclaration md : td.getMethods()) {
                    if (md.findAncestor(TypeDeclaration.class).orElse(null) != td) {
                        continue;                          // 안쪽 클래스의 메서드는 그 클래스에서
                    }
                    methods.add(method(md));
                }
                c.put("methods", methods);
                out.add(c);
            }
        }
        return out;
    }

    private Map<String, Object> method(MethodDeclaration md) {
        Map<String, Object> m = Json.obj();
        m.put("name", md.getNameAsString());
        m.put("line", line(md.getName()));
        m.put("ann_line", line(md));
        m.put("annotations", annotations(md));
        List<Map<String, Object>> params = new ArrayList<>();
        for (Parameter p : md.getParameters()) {
            Map<String, Object> pm = Json.obj();
            pm.put("name", p.getNameAsString());
            pm.put("type", simpleType(p.getType().asString()));
            pm.put("annotations", annotations(p));
            params.add(pm);
        }
        m.put("params", params);
        m.put("return_type", simpleType(md.getType().asString()));
        m.put("has_body", md.getBody().isPresent());
        Node body = md.getBody().orElse(null);
        List<Map<String, Object>> returns = new ArrayList<>();
        List<Map<String, Object>> attrs = new ArrayList<>();
        List<Map<String, Object>> throwsList = new ArrayList<>();
        List<Integer> rejects = new ArrayList<>();
        Integer hasErrors = null;
        if (body != null) {
            for (ReturnStmt rs : body.findAll(ReturnStmt.class)) {
                if (insideLambda(rs, md) || rs.getExpression().isEmpty()) {
                    continue;
                }
                returns.add(returnInfo(rs.getExpression().get(), contextOf(rs, md), line(rs), isJson(md)));
            }
            for (MethodCallExpr call : body.findAll(MethodCallExpr.class)) {
                String n = call.getNameAsString();
                if ((n.equals("addAttribute") || n.equals("addFlashAttribute")) && call.getArguments().size() >= 1
                        && call.getArgument(0) instanceof StringLiteralExpr s) {
                    Map<String, Object> a = Json.obj();
                    a.put("name", s.asString());
                    a.put("line", line(call.getName()));
                    a.put("context", contextOf(call, md));
                    a.put("flash", n.equals("addFlashAttribute"));
                    attrs.add(a);
                }
                if ((n.equals("reject") || n.equals("rejectValue")) && call.getScope().isPresent()) {
                    String scope = call.getScope().get().toString();
                    boolean onBinding = md.getParameters().stream().anyMatch(p -> p.getNameAsString().equals(scope)
                            && (simpleType(p.getType().asString()).equals("BindingResult") || simpleType(p.getType().asString()).equals("Errors")));
                    if (onBinding) {
                        rejects.add(line(call.getName()));
                    }
                }
            }
            for (IfStmt is : body.findAll(IfStmt.class)) {
                if (hasErrors == null && is.getCondition().toString().contains("hasErrors")) {
                    hasErrors = line(is);
                }
            }
            for (ObjectCreationExpr oc : body.findAll(ObjectCreationExpr.class)) {
                String type = oc.getType().getNameAsString();
                if (!type.endsWith("Exception") && !type.endsWith("Error")) {
                    continue;
                }
                String msg = oc.getArguments().stream().filter(a -> a instanceof StringLiteralExpr)
                        .map(a -> ((StringLiteralExpr) a).asString()).findFirst().orElse(null);
                if (msg == null) {
                    continue;
                }
                String ctx;
                Node anchor;
                if (oc.getParentNode().orElse(null) instanceof ThrowStmt ts) {
                    ctx = contextOf(ts, md);
                    anchor = ts;
                } else {
                    Optional<LambdaExpr> lambda = oc.findAncestor(LambdaExpr.class);
                    Optional<Node> holder = lambda.flatMap(Node::getParentNode);
                    if (holder.isPresent() && holder.get() instanceof MethodCallExpr mc && mc.getNameAsString().startsWith("orElseThrow")) {
                        String base = contextOf(mc, md);
                        ctx = (base.equals("정상 흐름") ? "" : base + ", ") + "조회 결과가 없으면(orElseThrow)";
                        anchor = oc;
                    } else {
                        continue;
                    }
                }
                Map<String, Object> t = Json.obj();
                t.put("exception", type);
                t.put("message", msg);
                t.put("line", line(anchor));
                t.put("context", ctx);
                throwsList.add(t);
            }
        }
        m.put("returns", returns);
        m.put("model_attrs", attrs);
        m.put("throws", throwsList);
        m.put("rejects", rejects);
        m.put("has_errors_line", hasErrors);
        return m;
    }

    private static boolean isJson(MethodDeclaration md) {
        boolean rest = md.findAncestor(TypeDeclaration.class).map(t -> t.isAnnotationPresent("RestController")).orElse(false);
        return rest || md.isAnnotationPresent("ResponseBody") || simpleType(md.getType().asString()).equals("ResponseEntity");
    }

    private static Map<String, Object> returnInfo(Expression e, String ctx, int line, boolean json) {
        Map<String, Object> r = Json.obj();
        String kind;
        String value;
        if (e instanceof StringLiteralExpr || e instanceof BinaryExpr || e instanceof TextBlockLiteralExpr) {
            String v = render(e);
            if (v.startsWith("redirect:")) {
                kind = "redirect";
                value = v.substring("redirect:".length());
            } else if (v.startsWith("forward:")) {
                kind = "forward";
                value = v.substring("forward:".length());
            } else if (json) {
                kind = "body";
                value = shorten(v, 40);
            } else {
                kind = "view";
                value = v;
            }
        } else {
            kind = "body";
            value = shorten(e.toString(), 50);
        }
        r.put("kind", kind);
        r.put("value", value);
        r.put("context", ctx);
        r.put("line", line);
        return r;
    }

    // =================================================================== 콜그래프

    List<Map<String, Object>> calls() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (CompilationUnit cu : units) {
            String file = rel(cu);
            List<MethodCallExpr> found = cu.findAll(MethodCallExpr.class);
            Map<String, List<MethodCallExpr>> groups = new LinkedHashMap<>();
            for (MethodCallExpr c : found) {
                groups.computeIfAbsent(line(c.getName()) + "|" + c.getNameAsString(), k -> new ArrayList<>()).add(c);
            }
            Map<MethodCallExpr, Integer> index = new IdentityHashMap<>();
            for (List<MethodCallExpr> g : groups.values()) {
                g.sort(Comparator.comparingInt(x -> x.getName().getBegin().map(p -> p.column).orElse(0)));
                for (int i = 0; i < g.size(); i++) {
                    index.put(g.get(i), i);
                }
            }
            for (MethodCallExpr mce : found) {
                out.add(call(file, mce, index.getOrDefault(mce, 0)));
            }
        }
        return out;
    }

    private Map<String, Object> call(String file, MethodCallExpr mce, int idx) {
        Map<String, Object> c = Json.obj();
        c.put("file", file);
        c.put("line", line(mce.getName()));
        c.put("name", mce.getNameAsString());
        c.put("index", idx);
        c.put("receiver", mce.getScope().map(Node::toString).orElse(null));
        c.put("args", mce.getArguments().size());
        Optional<CallableDeclaration> caller = mce.findAncestor(CallableDeclaration.class);
        c.put("caller_class", mce.findAncestor(TypeDeclaration.class).map(TypeDeclaration::getNameAsString).orElse(null));
        c.put("caller_method", caller.map(CallableDeclaration::getNameAsString).orElse(null));
        c.put("caller_line", caller.map(cd -> line(cd.getName())).orElse(null));
        c.put("context", caller.map(cd -> contextOf(mce, cd)).orElse("정상 흐름"));
        c.put("first_string", mce.getArguments().stream().filter(a -> a instanceof StringLiteralExpr)
                .map(a -> ((StringLiteralExpr) a).asString()).findFirst().orElse(null));
        String receiverType = null;
        if (mce.getScope().isPresent() && !(mce.getScope().get() instanceof ThisExpr)) {
            try {
                ResolvedType rt = mce.getScope().get().calculateResolvedType();
                if (rt.isReferenceType()) {
                    receiverType = simpleType(rt.asReferenceType().getQualifiedName());
                }
            } catch (Throwable ignored) {
                // 타입을 못 풀면 비워 둔다
            }
        }
        c.put("receiver_type", receiverType);
        String note;
        try {
            ResolvedMethodDeclaration r = mce.resolve();
            ResolvedReferenceTypeDeclaration d = r.declaringType();
            c.put("resolved", true);
            c.put("declaring_type", d.getName());
            c.put("declaring_qualified", d.getQualifiedName());
            c.put("declaring_kind", d.isInterface() ? "interface" : d.isEnum() ? "enum" : "class");
            c.put("signature", r.getQualifiedSignature());
            List<Map<String, Object>> impls = new ArrayList<>();
            if (r instanceof JavaParserMethodDeclaration jp) {
                MethodDeclaration md = jp.getWrappedNode();
                c.put("decl_file", md.findCompilationUnit().map(this::rel).orElse(null));
                c.put("decl_line", line(md.getName()));
                if (d.isInterface()) {
                    for (ClassOrInterfaceDeclaration impl : implsByIface.getOrDefault(d.getName(), List.of())) {
                        for (MethodDeclaration im : impl.getMethodsByName(mce.getNameAsString())) {
                            if (im.getParameters().size() == r.getNumberOfParams()) {
                                Map<String, Object> i = Json.obj();
                                i.put("file", im.findCompilationUnit().map(this::rel).orElse(null));
                                i.put("line", line(im.getName()));
                                i.put("type", impl.getNameAsString());
                                impls.add(i);
                            }
                        }
                    }
                }
            } else {
                c.put("decl_file", null);
                c.put("decl_line", null);
            }
            c.put("impls", impls);
            boolean springData = d.isInterface() && isSpringData(d);
            note = springData ? "spring_data_derived" : d.isInterface() ? "interface_normal" : "resolved";
        } catch (Throwable t) {                    // UnsolvedSymbolException, UnsupportedOperationException, StackOverflowError …
            c.put("resolved", false);
            c.put("error", t.getClass().getSimpleName());
            note = "unresolved";
        }
        c.put("note", note);
        callStats.merge(note, 1, Integer::sum);
        return c;
    }

    private static boolean isSpringData(ResolvedReferenceTypeDeclaration d) {
        try {
            for (ResolvedReferenceType a : d.asInterface().getAllAncestors()) {
                String q = a.getQualifiedName();
                if (q.startsWith("org.springframework.data.repository") || q.startsWith("org.springframework.data.jpa.repository")) {
                    return true;
                }
            }
        } catch (Throwable ignored) {
            // 라이브러리 classpath가 없으면 조상을 못 푼다 → Python이 extends 이름으로 다시 본다
        }
        return false;
    }

    // =================================================================== 컨트롤러 경로

    List<Map<String, Object>> routes() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (CompilationUnit cu : units) {
            for (ClassOrInterfaceDeclaration c : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                if (!c.isAnnotationPresent("Controller") && !c.isAnnotationPresent("RestController")) {
                    continue;
                }
                List<String> prefixes = c.getAnnotationByName("RequestMapping").map(Backend::annotationStrings).orElse(List.of());
                if (prefixes.isEmpty()) {
                    prefixes = List.of("");
                }
                for (MethodDeclaration md : c.getMethods()) {
                    Optional<AnnotationExpr> ann = md.getAnnotations().stream()
                            .filter(a -> MAPPINGS.containsKey(a.getNameAsString())).findFirst();
                    if (ann.isEmpty()) {
                        continue;
                    }
                    out.add(route(c, md, ann.get(), prefixes));
                }
            }
        }
        return out;
    }

    private Map<String, Object> route(ClassOrInterfaceDeclaration c, MethodDeclaration md, AnnotationExpr ann, List<String> prefixes) {
        String http = MAPPINGS.get(ann.getNameAsString());
        if (http.isEmpty()) {
            List<String> ms = new ArrayList<>();
            java.util.regex.Matcher m = java.util.regex.Pattern.compile("RequestMethod\\.(\\w+)").matcher(ann.toString());
            while (m.find()) {
                ms.add(m.group(1));
            }
            http = ms.isEmpty() ? "ANY" : String.join("/", ms);
        }
        List<String> subs = annotationStrings(ann);
        if (subs.isEmpty()) {
            subs = List.of("");
        }
        List<String> paths = new ArrayList<>();
        for (String p : prefixes) {
            for (String s : subs) {
                String joined = (stripEnd(p) + "/" + stripStart(s));
                joined = stripEnd(joined);
                paths.add(joined.isEmpty() ? "/" : joined);
            }
        }
        Map<String, Object> r = Json.obj();
        r.put("controller", c.getNameAsString());
        r.put("method", md.getNameAsString());
        r.put("file", rel(md.findCompilationUnit().orElseThrow()));
        r.put("line", line(ann));
        r.put("method_line", line(md.getName()));
        r.put("http", http);
        r.put("paths", paths);
        r.put("json", isJson(md));
        List<String> valid = new ArrayList<>();
        List<String> forms = new ArrayList<>();
        List<String> reqParams = new ArrayList<>();
        List<Map<String, Object>> attrs = new ArrayList<>();
        boolean bindingResult = false;
        for (Parameter p : md.getParameters()) {
            String type = simpleType(p.getType().asString());
            if (type.equals("BindingResult") || type.equals("Errors")) {
                bindingResult = true;
            } else if (p.isAnnotationPresent("RequestParam") || p.isAnnotationPresent("PathVariable")) {
                AnnotationExpr a = p.getAnnotationByName("RequestParam").orElseGet(() -> p.getAnnotationByName("PathVariable").get());
                List<String> names = annotationStrings(a);
                reqParams.add(names.isEmpty() ? p.getNameAsString() : names.get(0));
            } else if (p.isAnnotationPresent("RequestBody")) {
                continue;
            } else if (!FRAMEWORK_PARAM_TYPES.contains(type)) {
                forms.add(type);
                if (p.isAnnotationPresent("Valid") || p.isAnnotationPresent("Validated")) {
                    valid.add(type);
                }
                List<String> named = p.getAnnotationByName("ModelAttribute").map(Backend::annotationStrings).orElse(List.of());
                Map<String, Object> a = Json.obj();
                a.put("name", named.isEmpty() ? decap(type) : named.get(0));
                a.put("line", line(md.getName()));
                a.put("file", rel(md.findCompilationUnit().orElseThrow()));
                a.put("context", "요청마다");
                a.put("via", null);
                a.put("flash", false);
                a.put("implicit", true);
                attrs.add(a);
            }
        }
        r.put("valid_params", valid);
        r.put("form_params", forms);
        r.put("request_params", reqParams);
        r.put("binding_result", bindingResult);
        Map<String, Object> self = method(md);
        r.put("returns", self.get("returns"));
        r.put("has_errors_line", self.get("has_errors_line"));
        r.put("rejects", self.get("rejects"));
        List<String> helpers = new ArrayList<>();
        collectAttrs(c, md, null, null, new HashSet<>(), attrs, helpers);
        r.put("attrs", attrs);
        r.put("helpers", helpers);
        return r;
    }

    /** 모델에 넣는 값. 같은 컨트롤러의 헬퍼 메서드 안에서 넣은 값은 헬퍼를 부른 자리의 분기를 문맥으로 쓴다
     *  (v5~v7의 "호출자를 거슬러 올라가 뷰 찾기"를 반대 방향으로 적용). */
    private void collectAttrs(ClassOrInterfaceDeclaration c, MethodDeclaration md, String via, String ctxOverride,
                              Set<String> seen, List<Map<String, Object>> out, List<String> helpers) {
        if (!seen.add(md.getNameAsString() + ":" + line(md.getName())) || md.getBody().isEmpty()) {
            return;
        }
        for (MethodCallExpr call : md.getBody().get().findAll(MethodCallExpr.class)) {
            String n = call.getNameAsString();
            if ((n.equals("addAttribute") || n.equals("addFlashAttribute")) && !call.getArguments().isEmpty()
                    && call.getArgument(0) instanceof StringLiteralExpr s) {
                Map<String, Object> a = Json.obj();
                a.put("name", s.asString());
                a.put("line", line(call.getName()));
                a.put("file", rel(md.findCompilationUnit().orElseThrow()));
                a.put("context", ctxOverride != null ? ctxOverride : contextOf(call, md));
                a.put("via", via);
                a.put("flash", n.equals("addFlashAttribute"));
                a.put("implicit", false);
                out.add(a);
            } else if (call.getScope().isEmpty() || call.getScope().get() instanceof ThisExpr) {
                for (MethodDeclaration helper : c.getMethodsByName(n)) {
                    boolean mapped = helper.getAnnotations().stream().anyMatch(a -> MAPPINGS.containsKey(a.getNameAsString()));
                    if (!mapped) {
                        if (!helpers.contains(helper.getNameAsString())) {
                            helpers.add(helper.getNameAsString());
                        }
                        collectAttrs(c, helper, helper.getNameAsString(),
                                ctxOverride != null ? ctxOverride : contextOf(call, md), seen, out, helpers);
                    }
                }
            }
        }
    }

    // =================================================================== Controller → 템플릿 바인딩

    List<Map<String, Object>> bindings(List<Map<String, Object>> routes) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> r : routes) {
            String label = r.get("http") + " " + String.join(", ", (List<String>) r.get("paths"));
            String handler = r.get("controller") + "." + r.get("method");
            for (Map<String, Object> ret : (List<Map<String, Object>>) r.get("returns")) {
                String kind = (String) ret.get("kind");
                if (!kind.equals("view") && !kind.equals("forward")) {
                    continue;
                }
                String view = stripStart(stripEnd((String) ret.get("value")));
                String ctx = (String) ret.get("context");
                Templates.Template t = templatesByView.get(view);
                if (t == null) {
                    Map<String, Object> b = bindingBase(label, handler, r.get("file"), ret.get("line"), ctx, view);
                    b.put("kind", "template_missing");
                    out.add(b);
                    continue;
                }
                List<Templates.Template> parts = withFragments(t);
                List<String> fragViews = new ArrayList<>();
                for (int i = 1; i < parts.size(); i++) {
                    fragViews.add(parts.get(i).view);
                }
                Set<String> seenNames = new HashSet<>();
                for (Map<String, Object> a : (List<Map<String, Object>>) r.get("attrs")) {
                    String actx = (String) a.get("context");
                    boolean reaches = !(Boolean) a.get("flash") && ((Boolean) a.get("implicit")
                            || actx.equals("정상 흐름") || actx.equals(ctx) || ctx.startsWith(actx));
                    String name = (String) a.get("name");
                    if (!reaches || !seenNames.add(name)) {
                        continue;
                    }
                    Map<String, Object> ref = null;
                    for (Templates.Template part : parts) {
                        for (Map<String, Object> rf : part.refs) {
                            if (name.equals(rf.get("name"))) {
                                ref = Json.obj();
                                ref.put("file", part.file);
                                ref.put("line", rf.get("line"));
                                ref.put("expr", rf.get("expr"));
                                break;
                            }
                        }
                        if (ref != null) {
                            break;
                        }
                    }
                    Map<String, Object> b = bindingBase(label, handler, a.get("file"), a.get("line"), ctx, view);
                    b.put("kind", "model_attr");
                    b.put("attr_name", name);
                    b.put("implicit", a.get("implicit"));
                    b.put("target_template", t.file);
                    b.put("fragments", fragViews);
                    b.put("status", ref != null ? "confirmed" : "mismatch");
                    b.put("ref", ref);
                    out.add(b);
                }
                List<String> valid = (List<String>) r.get("valid_params");
                if (ctx.startsWith("입력값 검사 실패") && !valid.isEmpty()) {
                    List<Map<String, Object>> outputs = new ArrayList<>();
                    for (Templates.Template part : parts) {
                        for (Map<String, Object> eo : part.errorOutputs) {
                            Map<String, Object> o = Json.obj();
                            o.put("file", part.file);
                            o.put("line", eo.get("line"));
                            o.put("expr", eo.get("expr"));
                            outputs.add(o);
                        }
                    }
                    Integer hel = (Integer) r.get("has_errors_line");
                    Map<String, Object> b = bindingBase(label, handler, r.get("file"), hel != null ? hel : ret.get("line"), ctx, view);
                    b.put("kind", "validation_output");
                    b.put("forms", valid);
                    b.put("target_template", t.file);
                    b.put("fragments", fragViews);
                    b.put("error_outputs", outputs);
                    b.put("rejects", r.get("rejects"));
                    out.add(b);
                }
            }
        }
        return out;
    }

    private static Map<String, Object> bindingBase(String label, String handler, Object file, Object line, String ctx, String view) {
        Map<String, Object> b = Json.obj();
        b.put("route", label);
        b.put("handler", handler);
        b.put("file", file);
        b.put("line", line);
        b.put("context", ctx);
        b.put("view", view);
        return b;
    }

    private List<Templates.Template> withFragments(Templates.Template t) {
        List<Templates.Template> out = new ArrayList<>(List.of(t));
        Set<String> seen = new HashSet<>(Set.of(t.view));
        List<String> todo = new ArrayList<>();
        t.includes.forEach(i -> todo.add((String) i.get("view")));
        while (!todo.isEmpty()) {
            String v = todo.remove(todo.size() - 1);
            if (!seen.add(v)) {
                continue;
            }
            Templates.Template ft = templatesByView.get(v);
            if (ft != null) {
                out.add(ft);
                ft.includes.forEach(i -> todo.add((String) i.get("view")));
            }
        }
        return out;
    }

    // =================================================================== 보안 설정

    List<Map<String, Object>> security() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (CompilationUnit cu : units) {
            String file = rel(cu);
            for (MethodCallExpr mce : cu.findAll(MethodCallExpr.class)) {
                String n = mce.getNameAsString();
                if (SECURITY_MATCHERS.contains(n)) {
                    Node parent = mce.getParentNode().orElse(null);
                    if (!(parent instanceof MethodCallExpr rule) || rule.getScope().orElse(null) != mce) {
                        continue;
                    }
                    Map<String, Object> s = Json.obj();
                    s.put("kind", "matcher");
                    s.put("file", file);
                    s.put("line", line(mce.getName()));
                    s.put("matcher", n);
                    List<String> methods = new ArrayList<>();
                    for (Expression a : mce.getArguments()) {
                        if (a instanceof FieldAccessExpr fa && fa.getScope().toString().endsWith("HttpMethod")) {
                            methods.add(fa.getNameAsString());
                        }
                    }
                    s.put("methods", methods);
                    s.put("paths", strings(mce.getArguments()));
                    s.put("rule", rule.getNameAsString());
                    s.put("rule_args", strings(rule.getArguments()));
                    out.add(s);
                } else if (SECURITY_CALLS.contains(n)) {
                    Map<String, Object> s = Json.obj();
                    s.put("kind", "call");
                    s.put("file", file);
                    s.put("line", line(mce.getName()));
                    s.put("name", n);
                    s.put("strings", strings(mce.getArguments()));
                    List<String> raw = new ArrayList<>();
                    mce.getArguments().forEach(a -> raw.add(shorten(a.toString(), 60)));
                    s.put("args", raw);
                    out.add(s);
                }
            }
        }
        return out;
    }

    // =================================================================== 공통 도우미

    /** 노드가 어떤 분기 안에 있는지: '입력값 검사 실패 시', '예외(IllegalArgumentException) 시', '조건 … 일 때'. */
    static String contextOf(Node node, Node stop) {
        List<String> tags = new ArrayList<>();
        Node child = node;
        Node p = node.getParentNode().orElse(null);
        while (p != null && p != stop && !(p instanceof CallableDeclaration)) {
            if (p instanceof CatchClause cc) {
                tags.add("예외(" + cc.getParameter().getType().asString() + ") 시");
            } else if (p instanceof IfStmt is && child != is.getCondition()) {
                String cond = is.getCondition().toString();
                boolean inElse = is.getElseStmt().isPresent() && is.getElseStmt().get() == child;
                if (cond.contains("hasErrors")) {
                    tags.add(inElse || cond.startsWith("!") ? "입력값 검사 통과 시" : "입력값 검사 실패 시");
                } else {
                    tags.add(shorten(cond, 60) + (inElse ? " 아닐 때" : " 일 때"));
                }
            }
            child = p;
            p = p.getParentNode().orElse(null);
        }
        Collections.reverse(tags);
        return tags.isEmpty() ? "정상 흐름" : String.join(", ", tags);
    }

    private static boolean insideLambda(Node n, Node method) {
        Node p = n.getParentNode().orElse(null);
        while (p != null && p != method) {
            if (p instanceof LambdaExpr) {
                return true;
            }
            p = p.getParentNode().orElse(null);
        }
        return false;
    }

    static String render(Expression e) {
        if (e instanceof StringLiteralExpr s) {
            return s.asString();
        }
        if (e instanceof TextBlockLiteralExpr tb) {
            return tb.asString();
        }
        if (e instanceof BinaryExpr b && b.getOperator() == BinaryExpr.Operator.PLUS) {
            return render(b.getLeft()) + render(b.getRight());
        }
        if (e instanceof EnclosedExpr en) {
            return render(en.getInner());
        }
        return "{" + shorten(e.toString(), 30) + "}";
    }

    static List<Map<String, Object>> annotations(NodeWithAnnotations<?> n) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (AnnotationExpr a : n.getAnnotations()) {
            Map<String, Object> m = Json.obj();
            m.put("name", a.getNameAsString().replaceAll(".*\\.", ""));
            m.put("line", line(a));
            m.put("values", annotationStrings(a));
            Map<String, Object> pairs = new LinkedHashMap<>();
            if (a instanceof NormalAnnotationExpr na) {
                for (MemberValuePair p : na.getPairs()) {
                    Expression v = p.getValue();
                    pairs.put(p.getNameAsString(), v instanceof StringLiteralExpr s ? s.asString() : v.toString());
                }
            } else if (a instanceof SingleMemberAnnotationExpr sa && !(sa.getMemberValue() instanceof StringLiteralExpr)
                    && !(sa.getMemberValue() instanceof ArrayInitializerExpr)) {
                pairs.put("value", sa.getMemberValue().toString());
            }
            m.put("pairs", pairs);
            out.add(m);
        }
        return out;
    }

    /** @GetMapping("/a"), @RequestMapping(value = {"/a", "/b"}), path = "/x" 의 문자열들 */
    static List<String> annotationStrings(AnnotationExpr a) {
        List<String> out = new ArrayList<>();
        if (a instanceof SingleMemberAnnotationExpr sa) {
            collectStrings(sa.getMemberValue(), out);
        } else if (a instanceof NormalAnnotationExpr na) {
            for (MemberValuePair p : na.getPairs()) {
                if (p.getNameAsString().equals("value") || p.getNameAsString().equals("path") || p.getNameAsString().equals("name")) {
                    collectStrings(p.getValue(), out);
                }
            }
        }
        return out;
    }

    private static void collectStrings(Expression e, List<String> out) {
        if (e instanceof StringLiteralExpr s) {
            out.add(s.asString());
        } else if (e instanceof ArrayInitializerExpr arr) {
            arr.getValues().forEach(v -> collectStrings(v, out));
        }
    }

    private static List<String> strings(NodeList<Expression> args) {
        List<String> out = new ArrayList<>();
        for (Expression a : args) {
            if (a instanceof StringLiteralExpr s) {
                out.add(s.asString());
            }
        }
        return out;
    }

    static int line(Node n) {
        return n.getBegin().map(p -> p.line).orElse(-1);
    }

    String rel(CompilationUnit cu) {
        return cu.getStorage().map(s -> src.relativize(s.getPath().toAbsolutePath().normalize()).toString().replace('\\', '/'))
                .orElse("?");
    }

    static String simpleType(String t) {
        String s = t.replaceAll("<.*>", "").replace("[]", "").strip();
        int i = s.lastIndexOf('.');
        return i >= 0 ? s.substring(i + 1) : s;
    }

    static String decap(String s) {
        return s.isEmpty() ? s : Character.toLowerCase(s.charAt(0)) + s.substring(1);
    }

    static String shorten(String s, int n) {
        String t = s.replaceAll("\\s+", " ").strip();
        return t.length() <= n ? t : t.substring(0, n - 1) + "…";
    }

    private static String stripEnd(String s) {
        String t = s;
        while (t.endsWith("/")) {
            t = t.substring(0, t.length() - 1);
        }
        return t;
    }

    private static String stripStart(String s) {
        String t = s;
        while (t.startsWith("/")) {
            t = t.substring(1);
        }
        return t;
    }
}
