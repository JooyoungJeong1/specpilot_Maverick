package demo.controller;

import demo.service.QnaService;
import java.security.Principal;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

// 가상 문의 앱 (mock). 실제 코드가 아니다.
@Controller
@RequestMapping("/qna")
public class QnaController {

    private final QnaService qnaService;

    public QnaController(QnaService qnaService) {
        this.qnaService = qnaService;
    }

    @GetMapping
    public String list(Model model, Principal principal) {
        model.addAttribute("items", qnaService.visibleTo(principal.getName()));
        return "qna/list";
    }

    @GetMapping("/new")
    public String writeForm() {
        return "qna/write";
    }

    @PostMapping
    public String create(QnaForm form, Principal principal) {
        qnaService.create(form, principal.getName());
        return "redirect:/qna";
    }

    @GetMapping("/{id}")
    public String detail(@PathVariable Long id, Model model) {
        model.addAttribute("qna", qnaService.get(id));
        return "qna/detail";
    }

    @PostMapping("/{id}/delete")
    public String delete(@PathVariable Long id) {
        qnaService.delete(id);
        return "redirect:/qna";
    }
}
