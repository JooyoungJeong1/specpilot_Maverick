document.addEventListener("DOMContentLoaded", () => {
    const titleInput = document.querySelector("#title");
    const saveButton = document.getElementById("saveButton");
    const update = () => {
        saveButton.disabled = !titleInput.value.trim();
    };
    titleInput.addEventListener("input", update);
});
