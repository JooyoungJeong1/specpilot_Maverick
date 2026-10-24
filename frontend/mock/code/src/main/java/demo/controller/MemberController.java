package demo.controller;

import demo.service.MemberService;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

// 가상 문의 앱 (mock). 실제 코드가 아니다.
@Controller
public class MemberController {

    private final MemberService memberService;

    public MemberController(MemberService memberService) {
        this.memberService = memberService;
    }

    @GetMapping("/login")
    public String loginForm() {
        return "member/login";
    }

    @GetMapping("/signup")
    public String signupForm() {
        return "member/signup";
    }

    @PostMapping("/signup")
    public String signup(SignupForm form) {
        memberService.join(form);
        return "redirect:/";
    }
}
