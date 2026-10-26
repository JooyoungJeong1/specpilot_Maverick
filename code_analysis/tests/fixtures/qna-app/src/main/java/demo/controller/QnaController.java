package demo.controller;

import demo.dto.QnaForm;
import demo.service.QnaService;

@Controller
@RequestMapping("/qna")
public class QnaController {
    private final QnaService qnaService;

    public QnaController(QnaService qnaService) {
        this.qnaService = qnaService;
    }

    @GetMapping("/new")
    public String form(Model model) {
        model.addAttribute("qnaForm", new QnaForm());
        return "qna/write";
    }

    @PostMapping
    public String create(@Valid @ModelAttribute QnaForm qnaForm, BindingResult bindingResult, Model model) {
        if (bindingResult.hasErrors()) {
            return "qna/write";
        }
        try {
            qnaService.create(qnaForm);
            return "redirect:/qna";
        } catch (IllegalArgumentException e) {
            model.addAttribute("errorMessage", e.getMessage());
            return "qna/write";
        }
    }

    @GetMapping
    public String list() {
        return "qna/list";
    }

    @PostMapping("/check")
    @ResponseBody
    public boolean check(@RequestParam("title") String title) {
        return true;
    }
}
