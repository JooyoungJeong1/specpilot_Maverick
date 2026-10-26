package demo.controller;

@Controller
public class AdminQnaController extends BaseController {

    @PostMapping("/admin/qna/{id}/close")
    public String close(@PathVariable Long id) {
        qnaService.close(id);
        return "redirect:/qna";
    }
}
