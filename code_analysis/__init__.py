"""SpecPilot 코드 분석: 소스 코드에서 ③ 정합성 판정에 같이 줄 "사실"을 뽑아 code_facts.json으로 쓴다.

LLM을 쓰지 않는다. 백엔드(.java + Thymeleaf)는 Java 분석기(JavaParser + Symbol Solver + Jsoup), 프론트엔드(.js)는 tree-sitter로 읽는다.
"""

__version__ = "0.2.0"
