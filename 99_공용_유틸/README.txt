공용 유틸

용도:
- PDF 인쇄용 외부 실행 파일 보관
- 여러 요청 스크립트에서 공용으로 참조
- `00_Codex_도구` 저장소용 Git 체크포인트 보조 스크립트 제공

구성:
- `SumatraPDF-3.5.2-64`
- `scripts\checkpoint_tool_repo.ps1`

예시:
- `powershell -ExecutionPolicy Bypass -File .\scripts\checkpoint_tool_repo.ps1 -Message "Checkpoint after runtime changes"`
