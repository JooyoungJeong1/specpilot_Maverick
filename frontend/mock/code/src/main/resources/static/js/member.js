// 가상 문의 앱 (mock). 실제 코드가 아니다.
const email = document.getElementById("email");
const password = document.getElementById("password");

function showError(input, message) {
  const box = document.getElementById(input.id + "Error");
  if (box) box.textContent = message;
}

email?.addEventListener("blur", () => {
  if (!/^[^@\s]+@[^@\s]+$/.test(email.value)) showError(email, "올바른 이메일 형식이 아닙니다.");
});

password?.addEventListener("blur", () => {
  if (password.value.length < 8) showError(password, "비밀번호는 8자 이상 입력해 주세요.");
});
