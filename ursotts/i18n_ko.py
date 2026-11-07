"""Korean strings for the desktop app (English text -> Korean).

Terms follow the approved translation table (Speak = 말하기, Batch = 일괄 변환,
Voice = 목소리, Pronunciation = 발음, Scripts = 스크립트, Render = 변환, narration = 내레이션).
Messages use the 합니다/하세요 style; buttons and menu items are short noun phrases.
Brand and technical terms stay in English: ursoTTS, Claude Code, VS Code, GitHub, WAV, MP3,
config.yaml, CLAUDE.md, scRNA-seq and the color theme names.

Keys are the exact English strings used in app.py (and the UserError texts in shared.py).
{placeholders} must be the same in key and value; scripts/check_i18n.py verifies that.
"""
from __future__ import annotations

import re

KO = {
    # ---- menus
    "File": "파일",
    "View": "보기",
    "Help": "도움말",
    "Open script…": "스크립트 열기…",
    "Save script": "스크립트 저장",
    "Save script as…": "다른 이름으로 저장…",
    "Show output folder": "출력 폴더 열기",
    "Create launcher…": "바로 가기 만들기…",
    "Quit": "종료",
    "Toggle output panel": "출력 패널 켜기/끄기",
    "Color Theme": "색 테마",
    "Choose color theme…": "색 테마 선택…",
    "Zoom in": "확대",
    "Zoom out": "축소",
    "Actual size": "실제 크기",
    "ursoTTS manual": "ursoTTS 설명서",
    "Open config.yaml": "config.yaml 열기",
    "About ursoTTS": "ursoTTS 정보",
    "ursoTTS {version} Korean edition": "ursoTTS {version} 한국어 버전",
    "Close": "닫기",
    "Settings (config.yaml)": "설정 (config.yaml)",
    "Zoom {percent}%": "배율 {percent}%",

    # ---- views, headings, tabs
    "SPEAK": "말하기", "Speak": "말하기",
    "BATCH": "일괄 변환", "Batch": "일괄 변환",
    "PRONUNCIATION": "발음", "Pronunciation": "발음",
    "CLAUDE CODE": "Claude Code", "Claude Code": "Claude Code",
    "pronunciation": "발음",
    "batch": "일괄 변환",
    "claude code": "Claude Code",
    "OUTPUT": "출력",
    "SCRIPT": "스크립트",
    "STATUS": "상태",
    "LENGTH": "길이",
    "Clear": "지우기",

    # ---- speak tab
    "Language": "언어",
    "Auto (English + Korean)": "자동 (영어 + 한국어)",
    "English": "영어",
    "Korean": "한국어",
    "Voices": "목소리",
    "English voice": "영어 목소리",
    "Korean voice": "한국어 목소리",
    "+ Add voice file…": "+ 목소리 파일 추가…",
    "↻ Refresh list": "↻ 목록 새로고침",
    "Speaking style": "말하기 스타일",
    "Expressiveness": "표현력",
    "calm … animated": "차분하게 … 생동감 있게",
    "Pacing": "속도",
    "slower … faster": "느리게 … 빠르게",
    "Variation": "변화",
    "steady … varied": "일정하게 … 다양하게",
    "Seed (same seed = same take)": "시드 (같은 시드 = 같은 결과)",
    "Output files": "출력 파일",
    "▶ Play": "▶ 재생",
    "■ Stop": "■ 중지",
    "▶": "▶",
    "Show": "열기",
    "Open…": "열기…",
    "Save as…": "다른 이름으로 저장…",
    "Generate narration": "내레이션 생성",
    "Play when done": "완료되면 재생",
    "Paste or type your narration here. Lines starting with # are not spoken.":
        "여기에 내레이션을 붙여넣거나 입력하세요. #으로 시작하는 줄은 읽지 않습니다.",
    "Generating narration…": "내레이션 생성 중…",
    "Type or paste some text first.": "먼저 텍스트를 입력하거나 붙여넣으세요.",
    "No voice found. Use “+ Add voice file…” to add a WAV or MP3 sample.":
        "목소리가 없습니다. “+ 목소리 파일 추가…”로 WAV 또는 MP3 샘플을 추가하세요.",
    "Made {seconds} s of audio in {took} s → {path}/": "오디오 {seconds}초를 {took}초 만에 만들었습니다 → {path}/",
    "Choose a voice sample (10–30 s of clear speech)": "목소리 샘플 선택 (또렷한 음성 10–30초)",
    "Voice sample": "목소리 샘플",
    "Added voice {name} (converted to mono 24 kHz, silence trimmed).":
        "목소리를 추가했습니다: {name} (모노 24 kHz로 변환, 앞뒤 무음 제거)",
    "Audio": "오디오",
    "Scripts": "스크립트",
    "All files": "모든 파일",
    "Text": "텍스트",
    "Markdown": "Markdown",
    "Open a script": "스크립트 열기",
    "Save script as": "다른 이름으로 스크립트 저장",
    "Save script": "스크립트 저장",
    "Could not save {path}:\n{error}": "저장할 수 없습니다: {path}\n{error}",
    "Saved {path}": "저장됨: {path}",
    "Unsaved changes": "저장하지 않은 변경 사항",
    "Save changes to {name} before closing it?": "닫기 전에 {name}의 변경 사항을 저장할까요?",

    # ---- pronunciation tab
    "Word or abbreviation": "단어 또는 약어",
    "Test sentence": "테스트 문장",
    "{word} is replaced by each spelling": "각 철자가 {word} 자리에 들어갑니다",
    "Suggest spellings": "철자 제안",
    "Tips": "팁",
    "Letters: each capital followed by a dot (R.N.A.).\n"
    "Word-like sounds: syllables joined by dots (NAN.og).\n"
    "Genes with a vowel 2nd letter: try the word form first.\n"
    "Korean: write the Hangul reading (피디엘원).":
        "글자 읽기: 대문자마다 점을 붙입니다 (R.N.A.).\n"
        "단어처럼 읽기: 음절을 점으로 잇습니다 (NAN.og).\n"
        "두 번째 글자가 모음인 유전자: 단어 형태를 먼저 시도하세요.\n"
        "한국어: 한글 발음으로 적습니다 (피디엘원).",
    "Versions to compare, one per line": "비교할 버전 (한 줄에 하나)",
    "Listen to all": "모두 듣기",
    "Sounds like (optional note)": "소리 메모 (선택 사항)",
    "Save to pronunciation rules": "발음 규칙에 저장",
    "Type a word first, for example DNA or NANOG.": "먼저 단어를 입력하세요. 예: DNA, NANOG",
    "Add at least one spelling, or click Suggest spellings.": "철자를 하나 이상 추가하거나 '철자 제안'을 누르세요.",
    "Generating versions…": "여러 버전 생성 중…",
    "Listen to the versions and choose the best one first.": "먼저 버전을 들어 보고 가장 좋은 것을 선택하세요.",
    "Saved {term} → {choice} (voice reads “{spoken}”). Scripts that use it are re-rendered on the next batch.":
        "{term} → {choice} 저장됨 (읽는 소리: “{spoken}”). 이 규칙을 쓰는 스크립트는 다음 일괄 변환 때 다시 변환됩니다.",

    "Saved rules": "저장된 규칙",
    "Load into editor": "편집 칸으로 불러오기",
    "Delete rule": "규칙 삭제",
    "No saved rules yet.": "저장된 규칙이 아직 없습니다.",
    "Select a rule in the list first.": "먼저 목록에서 규칙을 선택하세요.",
    "Delete the rule for “{term}”?": "“{term}” 규칙을 삭제할까요?",
    "Deleted the rule for {term}.": "{term} 규칙을 삭제했습니다.",
    "Open pronunciations.yaml": "pronunciations.yaml 열기",
    "No pronunciation rules file yet. Save a rule first.": "발음 규칙 파일이 아직 없습니다. 먼저 규칙을 저장하세요.",

    # ---- batch tab
    "Scripts folder": "스크립트 폴더",
    "Output folder": "출력 폴더",
    "Choose…": "선택…",
    "To make a new folder, use the New Folder button in the folder dialog.":
        "새 폴더를 만들려면 폴더 선택 창의 '새 폴더' 버튼을 사용하세요.",
    "Options": "옵션",
    "Render everything again": "전부 다시 변환",
    "Render all scripts": "모든 스크립트 변환",
    "Choose the scripts folder": "스크립트 폴더 선택",
    "Choose or create the output folder": "출력 폴더를 선택하거나 새로 만드세요",
    "Choose a scripts folder.": "스크립트 폴더를 선택하세요.",
    "up to date": "최신 상태",
    "will render": "변환 예정",
    "waiting…": "대기 중…",
    "done": "완료",
    "error (see OUTPUT)": "오류 (출력 패널 참조)",
    "{seconds} s": "{seconds}초",
    "{count} script(s) in {path} · {todo} to render": "{path}의 스크립트 {count}개 · 변환할 스크립트 {todo}개",
    "Folder not found:\n{path}": "폴더를 찾을 수 없습니다:\n{path}",
    "Voice sample not found:\n{paths}": "목소리 샘플을 찾을 수 없습니다:\n{paths}",
    "All {count} scripts are up to date. Tick “Render everything again” to redo them.":
        "스크립트 {count}개가 모두 최신입니다. 다시 하려면 “전부 다시 변환”을 선택하세요.",
    "Rendering {count} script(s)…": "스크립트 {count}개 변환 중…",
    "Rendered {ok} of {total} scripts. Files are in {path}/.":
        "스크립트 {total}개 중 {ok}개를 변환했습니다. 파일 위치: {path}/",

    # ---- Claude Code panel
    "Mode": "모드",
    "Ask (no changes)": "질문 (변경 없음)",
    "Edit the app": "앱 수정하기",
    "Continue conversation": "대화 이어가기",
    "After a change": "변경 후",
    "⟳ Restart app": "⟳ 앱 다시 시작",
    "↶ Undo last change": "↶ 마지막 변경 취소",
    "VS Code": "VS Code",
    "Open in VS Code": "VS Code에서 열기",
    "Copy request for VS Code": "VS Code용 요청 복사",
    "Ideas": "아이디어",
    "Make the sidebar 340 px wide": "사이드바 너비를 340px로 바꿔 주세요",
    "Use a blue status bar like VS Code": "상태 표시줄을 파란색으로 바꿔 주세요",
    "Add a Speed slider": "속도 슬라이더를 추가해 주세요",
    "Show each output file's length": "출력 파일마다 길이를 표시해 주세요",
    "Make the editor font size 14": "편집기 글꼴 크기를 14로 바꿔 주세요",
    "Ask Claude Code to change or explain this app": "Claude Code에게 이 앱의 변경이나 설명을 요청하세요",
    "Send to Claude": "Claude에게 보내기",
    "In the installed app, Claude can explain things but can't edit the app itself. "
    "To change the app, use the source version (pip install) and its Edit mode, or Claude Code in VS Code.\n"
    "This panel needs the Claude Code command line and your Claude login. "
    "Answers can take a minute or more. While Claude works, this panel shows "
    "only the names of the tools it uses (for example “Bash” or “Read”), "
    "not their details. Use Stop to cancel.":
        "설치된 앱에서는 Claude가 설명은 해 줄 수 있지만 앱 자체를 수정할 수는 없습니다. "
        "앱을 바꾸려면 소스 버전(pip install)의 수정 모드나 VS Code의 Claude Code를 사용하세요.\n"
        "이 패널을 쓰려면 Claude Code 명령줄 도구와 Claude 로그인이 필요합니다. "
        "답변에 1분 이상 걸릴 수 있습니다. 작업 중에는 Claude가 사용하는 도구 이름(예: “Bash”, “Read”)만 "
        "표시되고 자세한 내용은 보이지 않습니다. 취소하려면 ■ 중지를 누르세요.",
    "Uses the Claude Code command line with the same Claude login as VS Code. "
    "Edits are limited to reading and editing files; a backup is saved first, so Undo restores the previous version.":
        "VS Code와 같은 Claude 로그인으로 Claude Code 명령줄을 사용합니다. "
        "파일 읽기와 수정만 허용되며, 먼저 백업을 저장하므로 ‘마지막 변경 취소’로 이전 버전을 복원할 수 있습니다.",
    "The Claude Code command line (claude) isn't installed. Install it from code.claude.com/docs/en/setup, "
    "or use “Copy request for VS Code” and paste the request into the Claude panel in VS Code.":
        "Claude Code 명령줄(claude)이 설치되어 있지 않습니다. code.claude.com/docs/en/setup에서 설치하거나, "
        "“VS Code용 요청 복사”를 눌러 VS Code의 Claude 패널에 붙여넣으세요.",
    "Type what you'd like to change, or pick one of the ideas.": "변경하려는 내용을 입력하거나 아이디어 중 하나를 선택하세요.",
    "The Claude Code command line isn't installed.\n\nCopy the request so you can paste it into Claude Code in VS Code?":
        "Claude Code 명령줄이 설치되어 있지 않습니다.\n\nVS Code의 Claude Code에 붙여넣을 수 있도록 요청을 복사할까요?",
    "Claude is still working on the previous request.": "Claude가 이전 요청을 아직 처리하는 중입니다.",
    "\n▸ You ({mode}): ": "\n▸ 나 ({mode}): ",
    "ask": "질문",
    "edit": "수정",
    "Claude Code is working…": "Claude Code가 작업 중…",
    "Could not start Claude Code: {error}": "Claude Code를 시작할 수 없습니다: {error}",
    "Claude Code reported an error: {error}": "Claude Code에서 오류가 발생했습니다: {error}",
    "  done in {seconds:.0f} s": "  {seconds:.0f}초 만에 완료",
    "  changed: {files}": "  변경된 파일: {files}",
    "  Click “⟳ Restart app” to see the change, or “↶ Undo last change” to go back.":
        "  변경 사항을 보려면 “⟳ 앱 다시 시작”을, 되돌리려면 “↶ 마지막 변경 취소”를 누르세요.",
    "Claude Code changed: {files}": "Claude Code가 변경한 파일: {files}",
    "  no files were changed": "  변경된 파일이 없습니다",
    "  stopped": "  중지됨",
    "Undo": "실행 취소",
    "Undo last change": "마지막 변경 취소",
    "There's no saved version to go back to yet.": "되돌릴 저장된 버전이 아직 없습니다.",
    "Restore the app files saved before the last Claude edit ({name})? Then restart the app.":
        "마지막 Claude 수정 전에 저장된 앱 파일({name})을 복원할까요? 복원한 뒤 앱을 다시 시작하세요.",
    "  restored the previous version; click “⟳ Restart app”": "  이전 버전으로 복원했습니다. “⟳ 앱 다시 시작”을 누르세요",
    "Undo: restored app files from {name}": "실행 취소: {name}에서 앱 파일을 복원했습니다",
    "VS Code wasn't found. Open the project folder in VS Code yourself.":
        "VS Code를 찾을 수 없습니다. VS Code에서 프로젝트 폴더를 직접 여세요.",
    "(describe your change here)": "(여기에 변경 내용을 설명하세요)",
    "  copied: paste it into the Claude panel in VS Code": "  복사했습니다. VS Code의 Claude 패널에 붙여넣으세요",

    # ---- status bar, log, dialogs
    "  ursoTTS {version}   ·   engine: {engine}   ·   {model}": "  ursoTTS {version}   ·   엔진: {engine}   ·   {model}",
    "model ready": "모델 준비됨",
    "model loads on first run": "처음 실행할 때 모델 불러오기",
    "Ready   ·   {mod}J panel   ·   {mod}↵ run": "준비됨   ·   {mod}J 패널   ·   {mod}↵ 실행",
    "ursoTTS {version} desktop app. Project folder: {path}": "ursoTTS {version} 데스크톱 앱. 프로젝트 폴더: {path}",
    "The voice model loads the first time you generate; later runs are quick.":
        "목소리 모델은 처음 생성할 때 불러오며, 이후에는 빠릅니다.",
    "  generating… {tokens} tokens (≈{seconds:.1f} s of speech)": "  생성 중… 토큰 {tokens}개 (음성 약 {seconds:.1f}초)",
    " · {speed:.1f} tokens/s": " · 초당 토큰 {speed:.1f}개",
    "[ursotts] loading the voice model (first time only)…": "[ursotts] 목소리 모델 불러오는 중 (처음 한 번만)…",
    "[ursotts] voice model ready in {seconds:.1f} s": "[ursotts] 목소리 모델 준비 완료 ({seconds:.1f}초)",
    "Please wait: another task is still running.": "잠시만요, 다른 작업이 아직 실행 중입니다.",
    "ursoTTS": "ursoTTS",
    "ursoTTS is still working": "ursoTTS가 작업 중입니다",
    "Narration is still being made. Quit anyway and stop it?": "내레이션을 아직 만드는 중입니다. 그래도 종료하고 중단할까요?",
    "Create launcher": "바로 가기 만들기",
    "Launcher created": "바로 가기를 만들었습니다",
    "Created launcher: {where}": "바로 가기를 만들었습니다: {where}",
    "Created:\n{where}": "만든 위치:\n{where}",
    "Open it from Applications in your home folder, or drag it to the Dock.":
        "홈 폴더의 Applications에서 열거나 Dock으로 끌어다 놓으세요.",
    "Double-click it to open ursoTTS without a terminal.": "더블클릭하면 터미널 없이 ursoTTS가 열립니다.",
    "Select Color Theme": "색 테마 선택",
    "   (current)": "   (현재)",

    # ---- errors from shared.py (UserError)
    "The voice sample could not be read. Please record or upload it again.":
        "목소리 샘플을 읽을 수 없습니다. 다시 녹음하거나 업로드하세요.",
    "This audio file could not be converted. Try a WAV or MP3 file.":
        "이 오디오 파일을 변환할 수 없습니다. WAV 또는 MP3 파일을 사용해 보세요.",
    "Install ffmpeg to use this file type, or upload a WAV file.":
        "이 파일 형식을 사용하려면 ffmpeg를 설치하거나 WAV 파일을 사용하세요.",
    "The sample is only {seconds:.1f} s long. Record 10–30 seconds of speech.":
        "샘플이 {seconds:.1f}초밖에 되지 않습니다. 음성을 10–30초 녹음하세요.",

    # ---- the language switch itself (shown in both languages)
    "Restart ursoTTS to apply.": "다시 시작하면 적용됩니다.",

    # ---- program output lines (exact text)
    "[ursotts] warning: this chunk is unusually long for its text. The voice sample may contain silence, "
    "music or noise; try a cleaner sample.":
        "[ursotts] 경고: 이 구간이 텍스트에 비해 비정상적으로 깁니다. 목소리 샘플에 무음, 음악 또는 잡음이 있을 수 있으니 "
        "더 깨끗한 샘플을 사용해 보세요.",
    "  (ffmpeg not found - skipped MP3)": "  (ffmpeg를 찾을 수 없어 MP3를 건너뛰었습니다)",
}

# Program output whose text includes values (engine.py, pipeline.py, launcher.py): regex -> Korean template.
# Used by i18n.tr_line for the OUTPUT panel and error messages. Group "err" is translated recursively.
PATTERNS = [
    (re.compile(r"\[ursotts\] Chatterbox loaded on (?P<device>\S+) \(multilingual\)"),
     "[ursotts] Chatterbox를 불러왔습니다: {device} (다국어)"),
    (re.compile(r"\[ursotts\] Chatterbox loaded on (?P<device>\S+) \(English\)"),
     "[ursotts] Chatterbox를 불러왔습니다: {device} (영어)"),
    (re.compile(r"\[ursotts\] voice prepared from (?P<name>.+) in (?P<sec>[\d.]+) s"),
     "[ursotts] 목소리 준비 완료: {name} ({sec}초)"),
    (re.compile(r"\[ursotts\] (?P<lang>\w+): (?P<chars>\d+) characters -> (?P<secs>[\d.]+) s of audio in (?P<took>[\d.]+) s"),
     "[ursotts] {lang}: {chars}자 -> 오디오 {secs}초 ({took}초 소요)"),
    (re.compile(r"  -> (?P<secs>[\d.]+) s of audio in (?P<took>[\d.]+) s"),
     "  -> 오디오 {secs}초 ({took}초 소요)"),
    (re.compile(r"  !! failed: (?P<err>.*)", re.S),
     "  !! 실패: {err}"),
    (re.compile(r"Voice sample not found: (?P<path>.+)"),
     "목소리 샘플을 찾을 수 없습니다: {path}"),
    (re.compile(r"(?P<project>.+) doesn't look like the ursoTTS project folder \(no config\.yaml\)\. "
                r"Run this from inside the project folder\.", re.S),
     "ursoTTS 프로젝트 폴더가 아닌 것 같습니다 (config.yaml 없음): {project}\nursoTTS 프로젝트 폴더 안에서 실행하세요."),
]
