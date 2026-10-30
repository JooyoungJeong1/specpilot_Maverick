package com.thinktree.specpilot.analyzer;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Attribute;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.nodes.Node;
import org.jsoup.nodes.TextNode;
import org.jsoup.parser.Parser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Thymeleaf 템플릿 읽기 (Jsoup). 2주차 분석기의 template_refs(th:* 안의 모델 변수)를 늘려서
 * 줄 번호, 검증 오류 출력, 포함 조각, 스크립트, 폼·링크 주소, 입력란, 버튼·링크까지 뽑는다.
 */
final class Templates {

    static final Pattern MODEL_EXPR = Pattern.compile("[$*]\\{\\s*([A-Za-z_][A-Za-z0-9_]*)");
    private static final Set<String> SKIP_VARS = Set.of("param", "session", "application", "request", "response");
    private static final Pattern FRAGMENT = Pattern.compile("~\\{\\s*([\\w/\\-.]+)\\s*::");
    /** 조건 속성: 이 값이 참(또는 거짓)일 때만 요소가 그려진다 */
    private static final List<String> CONDITION_ATTRS = List.of("th:if", "th:unless", "data-th-if", "data-th-unless",
            "sec:authorize", "th:case", "data-th-case");
    /** 문구 요소로 보지 않는 태그 (버튼·링크·입력란은 controls·inputs에서 따로 다룬다) */
    private static final Set<String> NOT_TEXT_TAGS = Set.of("a", "button", "form", "input", "select", "textarea", "option",
            "script", "style", "title", "head", "html", "body", "meta", "link", "th:block");
    private static final Pattern FRAGMENT_PLAIN = Pattern.compile("^\\s*([\\w/\\-.]+)\\s*::");

    /** 템플릿 하나 */
    static final class Template {
        final String file;      // 소스 기준 상대 경로 (③과 같음)
        final String view;      // templates/ 아래 경로에서 .html을 뺀 이름 (컨트롤러가 반환하는 이름)
        String title = "";
        final List<String> headings = new ArrayList<>();
        boolean providesFragment;
        final List<Map<String, Object>> includes = new ArrayList<>();
        final List<Map<String, Object>> scripts = new ArrayList<>();
        final List<Map<String, Object>> refs = new ArrayList<>();
        final List<Map<String, Object>> errorOutputs = new ArrayList<>();
        final List<Map<String, Object>> urlRefs = new ArrayList<>();
        final List<Map<String, Object>> inputs = new ArrayList<>();
        final List<Map<String, Object>> controls = new ArrayList<>();
        final List<Map<String, Object>> texts = new ArrayList<>();      // 조건이 붙은 문구 요소 (v0.8.1)
        final Set<String> refNames = new LinkedHashSet<>();

        Template(String file, String view) {
            this.file = file;
            this.view = view;
        }

        Map<String, Object> toJson() {
            Map<String, Object> m = Json.obj();
            m.put("file", file);
            m.put("view", view);
            m.put("title", title);
            m.put("headings", headings);
            m.put("provides_fragment", providesFragment);
            m.put("includes", includes);
            m.put("scripts", scripts);
            m.put("refs", refs);
            m.put("error_outputs", errorOutputs);
            m.put("url_refs", urlRefs);
            m.put("inputs", inputs);
            m.put("controls", controls);
            m.put("texts", texts);
            return m;
        }
    }

    private Templates() {
    }

    static boolean isTemplate(String rel) {
        String low = rel.toLowerCase();
        return ("/" + rel).contains("/templates/") && (low.endsWith(".html") || low.endsWith(".htm"));
    }

    static Template parse(Path file, String rel) throws IOException {
        String html = Files.readString(file, StandardCharsets.UTF_8);
        int idx = rel.indexOf("templates/");
        String view = (idx >= 0 ? rel.substring(idx + "templates/".length()) : rel).replaceAll("\\.html?$", "");
        Template t = new Template(rel, view);
        Parser parser = Parser.htmlParser().setTrackPosition(true);
        Document doc = Jsoup.parse(html, "", parser);
        t.title = doc.title();
        for (Element h : doc.select("h1, h2")) {
            t.headings.add(h.text());
        }
        for (Element el : doc.getAllElements()) {
            int line = lineOf(el);
            for (Attribute a : el.attributes()) {
                String k = a.getKey().toLowerCase();
                String v = a.getValue();
                if (k.startsWith("th:") || k.startsWith("data-th-") || k.startsWith("sec:") || v.contains("${") || v.contains("*{")) {
                    addRefs(t, line, k, v);
                }
                if (k.equals("th:errors") || k.equals("data-th-errors")) {
                    t.errorOutputs.add(item("line", line, "expr", "th:errors=\"" + v + "\""));
                }
                if (k.equals("th:fragment")) {
                    t.providesFragment = true;
                }
                if (k.equals("th:replace") || k.equals("th:insert") || k.equals("th:include")) {
                    Matcher m = FRAGMENT.matcher(v);
                    Matcher m2 = FRAGMENT_PLAIN.matcher(v);
                    String frag = m.find() ? m.group(1) : (m2.find() ? m2.group(1) : null);
                    if (frag != null) {
                        t.includes.add(item("view", frag, "line", line));
                    }
                }
            }
            for (Node child : el.childNodes()) {                // [[${...}]] 인라인 표현식
                if (child instanceof TextNode tn) {
                    String text = tn.getWholeText();
                    if (text.contains("[[") || text.contains("[(")) {
                        addRefs(t, lineOf(tn, line), "inline", text.strip());
                    }
                }
            }
            String tag = el.tagName().toLowerCase();
            switch (tag) {
                case "script" -> {
                    String src = el.hasAttr("th:src") ? el.attr("th:src") : el.attr("src");
                    if (!src.isBlank()) {
                        t.scripts.add(item("url", src, "line", line));
                    }
                }
                case "form" -> addUrl(t, (el.hasAttr("method") ? el.attr("method") : "get").toUpperCase(),
                        el.hasAttr("th:action") ? el.attr("th:action") : el.attr("action"), line, "폼");
                case "a" -> addUrl(t, "GET", el.hasAttr("th:href") ? el.attr("th:href") : el.attr("href"), line, "링크");
                default -> {
                }
            }
            if (!NOT_TEXT_TAGS.contains(tag)) {                 // 조건이 붙은 문구: "없으면 숨김" 같은 표시 조건을 사실로 남긴다
                String condAttr = CONDITION_ATTRS.stream().filter(el::hasAttr).findFirst().orElse(null);
                if (condAttr != null) {
                    String own = el.ownText().strip();
                    String all = el.text().strip();
                    String thText = el.hasAttr("th:text") ? el.attr("th:text") : el.hasAttr("th:utext") ? el.attr("th:utext")
                            : el.hasAttr("data-th-text") ? el.attr("data-th-text") : null;
                    String text = !own.isEmpty() ? own : all;
                    if (!text.isEmpty() || thText != null) {
                        Map<String, Object> tx = item("tag", tag, "line", line);
                        tx.put("text", text.length() > 80 ? text.substring(0, 80) + "…" : text);
                        tx.put("cond_attr", condAttr);
                        tx.put("cond", el.attr(condAttr));
                        tx.put("th_text", thText);
                        t.texts.add(tx);
                    }
                }
            }
            if (tag.equals("input") || tag.equals("textarea") || tag.equals("select")) {
                t.inputs.add(item("line", line, "attrs", attrs(el)));
            }
            if (tag.equals("a") || tag.equals("button") || tag.equals("form")) {
                Map<String, Object> c = item("tag", tag, "line", line);
                c.put("text", el.text());
                Map<String, String> at = attrs(el);
                if (tag.equals("button")) {                    // 버튼이 속한 폼의 주소·메서드 (화면 이동 따라가기용)
                    Element form = el.closest("form");
                    String type = el.hasAttr("type") ? el.attr("type").toLowerCase() : "submit";
                    if (form != null && type.equals("submit")) {
                        at.put("_form_action", form.hasAttr("th:action") ? form.attr("th:action") : form.attr("action"));
                        at.put("_form_method", (form.hasAttr("method") ? form.attr("method") : "get").toUpperCase());
                    }
                }
                c.put("attrs", at);
                t.controls.add(c);
            }
        }
        return t;
    }

    private static void addRefs(Template t, int line, String attr, String value) {
        Matcher m = MODEL_EXPR.matcher(value);
        while (m.find()) {
            String name = m.group(1);
            if (!SKIP_VARS.contains(name)) {
                Map<String, Object> r = item("name", name, "line", line);
                r.put("attr", attr);
                r.put("expr", value.length() > 120 ? value.substring(0, 120) : value);
                t.refs.add(r);
                t.refNames.add(name);
            }
        }
        if (value.contains("#fields")) {
            t.errorOutputs.add(item("line", line, "expr", value.length() > 120 ? value.substring(0, 120) : value));
        }
    }

    private static void addUrl(Template t, String method, String raw, int line, String kind) {
        String url = normUrl(raw);
        if (url != null) {
            Map<String, Object> u = item("method", method, "url", url);
            u.put("line", line);
            u.put("kind", kind);
            t.urlRefs.add(u);
        }
    }

    /** @{/notices/{id}/edit(id=${notice.id})} → /notices/{}/edit, /login?error → /login. 경로가 아니면 null. */
    static String normUrl(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        String u = raw.strip();
        if (u.startsWith("@{") && u.endsWith("}")) {
            u = u.substring(2, u.length() - 1);
        }
        u = u.replaceAll("\\([^()]*\\)$", "");
        u = u.replaceAll("\\$\\{[^}]*}", "{}");
        u = u.replaceAll("\\{[^}/]*}", "{}");
        int q = u.indexOf('?');
        if (q >= 0) {
            u = u.substring(0, q);
        }
        int h = u.indexOf('#');
        if (h >= 0) {
            u = u.substring(0, h);
        }
        if (!u.startsWith("/")) {
            return null;
        }
        while (u.length() > 1 && u.endsWith("/")) {
            u = u.substring(0, u.length() - 1);
        }
        return u;
    }

    private static Map<String, String> attrs(Element el) {
        Map<String, String> m = new LinkedHashMap<>();
        for (Attribute a : el.attributes()) {
            m.put(a.getKey().toLowerCase(), a.getValue());
        }
        return m;
    }

    private static int lineOf(Node n) {
        return lineOf(n, 1);
    }

    private static int lineOf(Node n, int fallback) {
        try {
            int l = n.sourceRange().start().lineNumber();
            return l > 0 ? l : fallback;
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    static Map<String, Object> item(String k1, Object v1, String k2, Object v2) {
        Map<String, Object> m = Json.obj();
        m.put(k1, v1);
        m.put(k2, v2);
        return m;
    }
}
