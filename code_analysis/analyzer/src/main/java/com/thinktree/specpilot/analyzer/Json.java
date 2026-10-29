package com.thinktree.specpilot.analyzer;

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;

/** Map·List·문자열·숫자·불리언으로 만든 결과를 JSON 글자로 바꾼다 (외부 라이브러리 없이). */
final class Json {
    private Json() {
    }

    static Map<String, Object> obj() {
        return new LinkedHashMap<>();
    }

    static String write(Object value) {
        StringBuilder sb = new StringBuilder();
        write(sb, value, 0);
        return sb.append('\n').toString();
    }

    private static void write(StringBuilder sb, Object v, int depth) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof String s) {
            quote(sb, s);
        } else if (v instanceof Number || v instanceof Boolean) {
            sb.append(v);
        } else if (v instanceof Map<?, ?> m) {
            if (m.isEmpty()) {
                sb.append("{}");
                return;
            }
            boolean inline = depth >= 2;
            sb.append('{');
            int i = 0;
            for (Map.Entry<?, ?> e : m.entrySet()) {
                if (i++ > 0) {
                    sb.append(inline ? ", " : ",");
                }
                if (!inline) {
                    sb.append('\n').append("  ".repeat(depth + 1));
                }
                quote(sb, String.valueOf(e.getKey()));
                sb.append(": ");
                write(sb, e.getValue(), depth + 1);
            }
            if (!inline) {
                sb.append('\n').append("  ".repeat(depth));
            }
            sb.append('}');
        } else if (v instanceof Collection<?> c) {
            if (c.isEmpty()) {
                sb.append("[]");
                return;
            }
            boolean inline = depth >= 1 && c.stream().noneMatch(x -> x instanceof Map || x instanceof Collection);
            sb.append('[');
            int i = 0;
            for (Object x : c) {
                if (i++ > 0) {
                    sb.append(inline ? ", " : ",");
                }
                if (!inline) {
                    sb.append('\n').append("  ".repeat(depth + 1));
                }
                write(sb, x, depth + 1);
            }
            if (!inline) {
                sb.append('\n').append("  ".repeat(depth));
            }
            sb.append(']');
        } else {
            quote(sb, String.valueOf(v));
        }
    }

    private static void quote(StringBuilder sb, String s) {
        sb.append('"');
        for (char ch : s.toCharArray()) {
            switch (ch) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (ch < 0x20) {
                        sb.append(String.format("\\u%04x", (int) ch));
                    } else {
                        sb.append(ch);
                    }
                }
            }
        }
        sb.append('"');
    }
}
