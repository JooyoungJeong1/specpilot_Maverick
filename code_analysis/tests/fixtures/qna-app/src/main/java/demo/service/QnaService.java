package demo.service;

import demo.dto.QnaForm;
import demo.entity.Qna;
import demo.repository.QnaRepository;

@Service
public class QnaService {
    private final QnaRepository qnaRepository;
    private final NotifyService notifyService;

    public QnaService(QnaRepository qnaRepository, NotifyService notifyService) {
        this.qnaRepository = qnaRepository;
        this.notifyService = notifyService;
    }

    public Long create(QnaForm form) {
        if (qnaRepository.existsByTitle(form.getTitle())) {
            throw new IllegalArgumentException("이미 있는 제목입니다.");
        }
        notifyService.send("admin");
        return qnaRepository.save(new Qna(form)).getId();
    }

    public void close(Long id) {
        qnaRepository.deleteById(id);
    }
}
