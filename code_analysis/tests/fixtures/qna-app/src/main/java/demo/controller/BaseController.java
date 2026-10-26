package demo.controller;

import demo.service.QnaService;

public abstract class BaseController {
    @Autowired
    protected QnaService qnaService;
}
