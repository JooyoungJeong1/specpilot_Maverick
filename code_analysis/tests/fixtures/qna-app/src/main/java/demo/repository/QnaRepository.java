package demo.repository;

import demo.entity.Qna;

public interface QnaRepository extends JpaRepository<Qna, Long> {
    boolean existsByTitle(String title);
}
