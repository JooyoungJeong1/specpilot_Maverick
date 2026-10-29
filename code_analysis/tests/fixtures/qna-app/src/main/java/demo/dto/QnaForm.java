package demo.dto;

public class QnaForm {
    @NotBlank(message = "제목을 입력하세요")
    @Size(max = 30, message = "제목은 30자까지")
    private String title;

    private String content;
}
