// 가상 문의 앱 (mock). 실제 코드가 아니다.
const title = document.getElementById("title");
const content = document.getElementById("content");
const type = document.getElementById("type");

function showError(input, message) {
  document.getElementById(input.id + "Error").textContent = message;
}

title.addEventListener("blur", () => {
  if (!title.value.trim()) showError(title, "제목을 입력하세요");
});

content.addEventListener("blur", () => {
  if (content.value.length < 10) showError(content, "내용을 10자 이상 입력해주세요.");
});

type.addEventListener("change", () => type.classList.add("selected"));

function saveDraft() {
  localStorage.setItem("qnaDraft", JSON.stringify({ title: title.value, content: content.value }));
}
setInterval(saveDraft, 30000);
