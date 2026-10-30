document.addEventListener("DOMContentLoaded", () => {
    const gridElement = document.querySelector("#qnaGrid");
    const columnDefs = [
        { headerName: "번호", field: "no" },
        { headerName: "제목", field: "title" }
    ];
    const gridOptions = {
        columnDefs,
        pagination: true,
        paginationPageSize: 10,
        onRowClicked: () => {
            window.location.href = "/qna";
        }
    };
    agGrid.createGrid(gridElement, gridOptions);
});
