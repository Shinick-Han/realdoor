/* i18n.js — 한국어 병기 계층 (임시 보조. 정본은 영어다).
 *
 * ── 왜 이런 구조인가 ──────────────────────────────────────────────────────────────
 *
 * 1) 왜 app.js 의 문자열을 T(...) 로 감싸지 않았나.
 *    영어가 측정 대상이기 때문이다. app.js 의 영어 리터럴이 한 글자도 움직이지 않아야
 *    `git diff` 로 "영어는 그대로다"를 눈으로 확인할 수 있다. 그래서 번역은 렌더링이
 *    끝난 DOM 의 텍스트 노드를 사전에서 찾아 바꾸는 방식으로 얹는다. 사전의 키가
 *    영어 원문 그 자체이므로, 문자열이 app.js 에서 왔든 API 응답에서 왔든 상관없이
 *    같은 방식으로 잡힌다 — 거부(refusal) 문구가 서버에서 오는데도 번역되는 이유다.
 *
 * 2) 왜 MutationObserver 인가.
 *    app.js 는 상호작용마다 화면 일부를 다시 그린다. 그리는 쪽에 훅이 없으므로
 *    바깥에서 DOM 변화를 지켜보는 수밖에 없다. 우리가 바꾼 것 때문에 다시 우리가
 *    불리는 무한루프는 `applying` 플래그로 끊는다.
 *
 * 3) 왜 원문을 따로 보관하나.
 *    영어로 되돌릴 때 역사전을 쓰면 번역이 1:1이 아닌 순간 원문이 깨진다.
 *    바꾼 노드마다 원문을 들고 있다가 그대로 복원한다. 되돌린 결과는 영어 원문과
 *    문자 단위로 같아야 한다.
 *
 * 4) 왜 fetch 로 JSON 을 읽지 않나.
 *    file:// 에서 fetch 가 막힌다. 사전은 이 파일 안에 그대로 들어 있고,
 *    index.html 이 평범한 <script> 로 불러온다. 네트워크 요청은 0건이다.
 *
 * ── 번역 규율 ────────────────────────────────────────────────────────────────────
 * 준비도 상태를 판정 어휘로 옮기지 않는다. READY_TO_REVIEW 는 "검토 준비됨"이지
 * "적격"이 아니고, NEEDS_REVIEW 는 "확인 필요"이지 "부적격"이나 "보류"가 아니다.
 * "자격"이라는 단어는 오직 **하지 않는다고 말하는 문장**에서만 쓴다.
 */
(function () {
  "use strict";

  // ── 사전: 영어 원문(공백 정규화 후) → 한국어 ─────────────────────────────────
  // 키는 화면에 실제로 나타나는 영어 문장이다. 줄바꿈과 들여쓰기는 조회 전에
  // 공백 하나로 접히므로, index.html 처럼 여러 줄에 걸친 문장도 한 줄로 적으면 된다.
  var DICT = {

    // ── index.html: 머리말·고지·브랜드 ──────────────────────────────────────
    "Skip to main content": "본문으로 건너뛰기",
    "Ready, not eligible.": "준비되었는가를 말하고, 자격은 말하지 않습니다.",
    "This service reports document readiness only. It does not decide eligibility, and nothing on this screen means approved, denied, or ineligible. A qualified housing professional makes that determination.":
      "이 서비스는 서류의 준비도만 보고합니다. 자격을 판정하지 않으며, 이 화면의 어떤 내용도 승인·거절·부적격을 뜻하지 않습니다. 그 판정은 자격을 갖춘 주택 전문가가 합니다.",
    "Household": "세대",
    "Data source: loading…": "데이터 출처: 불러오는 중…",
    "About this service": "이 서비스에 대하여",
    "How this works, and how we tested it": "어떻게 동작하는지, 그리고 어떻게 검증했는지",

    // ── index.html: 시작 화면 ───────────────────────────────────────────────
    "Get your housing documents ready for a person to review":
      "주택 서류를 사람이 검토할 수 있는 상태로 만드세요",
    "RealDoor reads the documents for one household, shows you where on the page every value came from, and tells you what is still missing or out of date. It does not decide whether anyone qualifies for anything — a housing professional does that.":
      "RealDoor 는 한 세대의 서류를 읽고, 각 값이 문서의 어느 위치에서 나왔는지 보여주고, 아직 없거나 기한이 지난 것이 무엇인지 알려줍니다. 누가 무엇에 해당하는지는 판정하지 않습니다 — 그것은 주택 전문가가 합니다.",
    "Before you start": "시작하기 전에",
    "This walkthrough takes about ten minutes. The documents for the household you choose above are already loaded, so there is nothing to upload and nothing is sent anywhere. You can stop at any step and your work stays on this device.":
      "이 과정은 약 10분 걸립니다. 위에서 고른 세대의 서류는 이미 불러와 있으므로 올릴 것도 없고, 어디로도 전송되지 않습니다. 어느 단계에서든 멈출 수 있고 작업 내용은 이 기기에 남습니다.",
    "What happens, in order": "무슨 일이 어떤 순서로 일어나는지",

    // ── index.html: 각 단계의 제목과 안내문 ─────────────────────────────────
    "Step 1 of 6": "6단계 중 1단계",
    "Step 2 of 6": "6단계 중 2단계",
    "Step 3 of 6": "6단계 중 3단계",
    "Step 4 of 6": "6단계 중 4단계",
    "Step 5 of 6": "6단계 중 5단계",
    "Step 6 of 6": "6단계 중 6단계",

    "Check the values we read from your documents": "서류에서 읽어낸 값을 확인하세요",
    "Each value below is shown together with the box on the page it was read from. Choose a field name to light up its box. Nothing here is inferred about the person.":
      "아래의 각 값은 그것을 읽어낸 문서상의 영역과 함께 표시됩니다. 항목 이름을 고르면 해당 영역이 켜집니다. 여기에서 사람에 대해 추측한 것은 하나도 없습니다.",

    "Correct a value we read wrong": "잘못 읽은 값을 바로잡으세요",

    "Ask what a housing rule says": "주택 규칙이 뭐라고 하는지 물어보세요",
    "Every answer carries its rule id, the authority behind it, the date it took effect, and where in the source it is written.":
      "모든 답변에는 규칙 id, 그 근거가 되는 기관, 시행일, 그리고 원문의 어디에 적혀 있는지가 함께 붙습니다.",

    "See how your yearly income figure was worked out": "연 소득 금액이 어떻게 산출되었는지 보세요",
    "Inputs, formula, result, threshold, comparison, effective date. A comparison is not a determination.":
      "입력값, 계산식, 결과, 기준액, 비교, 시행일. 비교는 판정이 아닙니다.",

    "See what is missing or out of date": "무엇이 없거나 기한이 지났는지 보세요",
    "What is present, what is missing, what has expired, and what could not be dated — with the one thing you can do about each.":
      "무엇이 있고, 무엇이 없고, 무엇의 기한이 지났고, 무엇의 날짜를 확정할 수 없었는지 — 각각에 대해 할 수 있는 한 가지와 함께.",

    "Check what we found, then take your packet": "찾아낸 내용을 확인하고, 서류 묶음을 받으세요",
    "This is everything the earlier steps produced, in one place. Change anything that is wrong before you download it.":
      "앞 단계들이 만들어낸 모든 것이 한자리에 있습니다. 내려받기 전에 틀린 것을 고치세요.",

    // ── index.html: 심사위원 화면 ───────────────────────────────────────────
    "Not part of the renter's six steps": "세입자의 6단계에는 포함되지 않는 화면",
    "This page is for anyone checking the service rather than using it. Every control below can be triggered here and its actual response shown — a disclaimer is not a control. Underneath are our own measurements, printed as they came out.":
      "이 화면은 서비스를 쓰는 사람이 아니라 점검하는 사람을 위한 것입니다. 아래의 모든 통제는 여기서 직접 실행해 실제 응답을 볼 수 있습니다 — 고지문은 통제가 아닙니다. 그 아래에는 우리가 직접 측정한 숫자가 나온 그대로 실려 있습니다.",
    "Where the challenge's six acceptance steps live": "과제의 6개 수용 단계가 어디에 있는지",
    "The challenge brief specifies a six-step acceptance demo. Our numbered walkthrough is written for the renter, not for that list, so the two do not line up one to one. This is the mapping.":
      "과제 설명서는 6단계 수용 데모를 요구합니다. 우리의 번호 매긴 진행 과정은 그 목록이 아니라 세입자를 위해 쓰여 있어서, 둘은 1대1로 맞아떨어지지 않습니다. 아래가 그 대응표입니다.",
    "1. Upload documents, show extraction evidence": "1. 서류 업로드, 추출 근거 제시",
    "— walkthrough step 1. The documents are pre-loaded rather than uploaded; every value carries the box on the page it came from.":
      "— 진행 과정 1단계. 서류는 업로드가 아니라 미리 불러와 있으며, 모든 값은 그것이 나온 문서상의 영역을 달고 있습니다.",
    "2. Edit one field, show downstream values update": "2. 한 항목 수정, 하위 값 갱신 제시",
    "— walkthrough step 2.": "— 진행 과정 2단계.",
    "3. Ask a rule question, show an authoritative citation": "3. 규칙 질문, 권위 있는 인용 제시",
    "— walkthrough step 3.": "— 진행 과정 3단계.",
    "4. Deterministic calculation with effective dates": "4. 시행일이 붙은 결정론적 계산",
    "— walkthrough step 4.": "— 진행 과정 4단계.",
    "5. Identify missing or expired items, export a packet": "5. 없거나 기한 지난 항목 식별, 서류 묶음 내보내기",
    "— walkthrough steps 5 and 6. We split it because reviewing what is open and taking the packet are two different decisions for the renter.":
      "— 진행 과정 5단계와 6단계. 남은 항목을 검토하는 일과 서류 묶음을 받는 일은 세입자에게 서로 다른 결정이라서 둘로 나눴습니다.",
    "6. Run the refusal, prompt-injection and session-deletion tests": "6. 거부·프롬프트 인젝션·세션 삭제 시험 실행",
    "—": "—",
    "this page, immediately below.": "바로 이 화면, 아래에 있습니다.",
    "It is not numbered in the walkthrough because it is not a task the renter performs. Both the adversarial suite and the static no-decision guard exercise these paths on every run.":
      "세입자가 수행하는 일이 아니기 때문에 진행 과정에 번호를 붙이지 않았습니다. 적대적 시험 묶음과 정적 무판정 가드가 매 실행마다 이 경로들을 통과시킵니다.",
    "The controls, demonstrated live": "통제를 실제로 실행해 보이기",
    "Our own numbers": "우리가 낸 숫자",
    "Our measured results, including the parts that were not run and the ones that came out badly. Published as measured.":
      "우리가 측정한 결과입니다. 실행하지 못한 항목과 나쁘게 나온 항목까지 포함합니다. 측정된 그대로 공개합니다.",

    // ── index.html: 사이드 레일과 푸터 ──────────────────────────────────────
    "What this system is unsure about": "이 시스템이 확신하지 못하는 것",
    "Always visible, never folded away. A system that knows something and does not say it is the failure this product exists to prevent.":
      "항상 보이고, 접어 숨기지 않습니다. 알면서 말하지 않는 시스템 — 그것이 이 제품이 막으려고 존재하는 실패입니다.",
    "About this build": "이 빌드에 대하여",

    // ── app.js: 진행 과정 목록의 설명문 ─────────────────────────────────────
    "See each value we read and the exact box on the page it came from.":
      "우리가 읽은 각 값과, 그것이 나온 문서상의 정확한 영역을 봅니다.",
    "Change anything we got wrong, and see whether it changed the numbers.":
      "우리가 틀린 것을 바꾸고, 그것이 숫자를 바꿨는지 봅니다.",
    "Get an answer with the rule id, the authority, and the date it took effect.":
      "규칙 id, 근거 기관, 시행일이 함께 붙은 답변을 받습니다.",
    "Inputs, formula, result and the threshold it is compared against.":
      "입력값, 계산식, 결과, 그리고 비교 대상이 되는 기준액.",
    "The full checklist, and the one thing you can do about each open item.":
      "전체 점검표와, 남은 항목마다 할 수 있는 한 가지.",
    "Review everything in one place, change what is wrong, then download it.":
      "모든 것을 한자리에서 검토하고, 틀린 것을 고친 뒤 내려받습니다.",

    // ── app.js: 단계 표시기의 짧은 이름 ─────────────────────────────────────
    "Your documents": "내 서류",
    "Corrections": "정정",
    "Rules": "규칙",
    "The calculation": "계산",
    "Missing or expired": "없음 또는 기한 지남",
    "Your packet": "내 서류 묶음",
    "Progress": "진행 상황",
    "— completed": "— 완료됨",
    "— current step": "— 현재 단계",
    "— not completed": "— 아직 안 됨",

    // ── app.js: 이동 버튼 ───────────────────────────────────────────────────
    "Start step 1": "1단계 시작",
    "Go back to where you were": "보던 곳으로 돌아가기",
    "Return to what we found": "찾아낸 내용으로 돌아가기",
    "Back to the start": "처음으로",

    // ── app.js: 준비도 상태 ────────────────────────────────────────────────
    // 판정 어휘 금지의 핵심 지점. "적격/부적격"이 아니라 "검토 준비"와 "남은 항목"이다.
    "Ready for a person to review": "사람이 검토할 준비가 되었습니다",
    "Every required document is present, current under the frozen 60-day convention, internally consistent, and traceable to a box on the page. This is not approval, and it is not an eligibility outcome.":
      "필요한 서류가 모두 있고, 동결된 60일 관행 기준으로 유효하며, 서로 모순이 없고, 문서상의 영역까지 추적됩니다. 이것은 승인이 아니며, 자격에 대한 결론도 아닙니다.",
    "Not ready yet — items still open": "아직 준비되지 않았습니다 — 남은 항목이 있습니다",
    "Something is missing, out of date, undatable, or inconsistent. This is not a refusal and it is not an eligibility outcome; it is a list of what to fix.":
      "무언가가 없거나, 기한이 지났거나, 날짜를 확정할 수 없거나, 서로 맞지 않습니다. 이것은 거절이 아니며 자격에 대한 결론도 아닙니다. 고쳐야 할 것들의 목록입니다.",

    // ── app.js: 비교 문장 ("비교는 판정이 아니다") ──────────────────────────
    "The annualized amount is at or below the frozen 60% threshold for this household size.":
      "연환산 금액이 이 세대원 수에 대한 동결된 60% 기준액 이하입니다.",
    "The annualized amount is above the frozen 60% threshold for this household size.":
      "연환산 금액이 이 세대원 수에 대한 동결된 60% 기준액을 넘습니다.",
    "No frozen threshold applies to this figure, so no comparison is made.":
      "이 금액에 적용되는 동결된 기준액이 없어서 비교하지 않습니다.",
    "A comparison is not a determination.": "비교는 판정이 아닙니다.",
    "This line says how one number sits against a frozen table. It does not say what happens next; a qualified housing professional decides that.":
      "이 줄은 숫자 하나가 동결된 표에 대해 어디에 놓이는지를 말할 뿐입니다. 그다음에 무슨 일이 일어나는지는 말하지 않습니다. 그것은 자격을 갖춘 주택 전문가가 정합니다.",

    // ── app.js: 항목 상태와 근거 종류 ───────────────────────────────────────
    "Present": "있음",
    "Missing": "없음",
    "Expired": "기한 지남",
    "Undatable": "날짜 확정 불가",
    "Unreadable": "읽지 못함",
    "Read from the document": "문서에서 읽음",
    "Confirmed by the renter": "세입자가 확인함",
    "Corrected by the renter": "세입자가 정정함",
    "High": "높음",
    "Low": "낮음",
    "Abstained — a person must supply this": "기권 — 사람이 입력해야 합니다",
    "Not read — a person must supply this": "읽지 못함 — 사람이 입력해야 합니다",

    // ── app.js: 검토 필요 사유의 사람용 제목 ────────────────────────────────
    "Your correction was recorded, but it was not used in the calculation":
      "정정을 기록했지만, 계산에는 쓰지 않았습니다",
    "Two figures on the same pay stub do not agree": "같은 급여명세서의 두 숫자가 서로 맞지 않습니다",
    "The gig income has nothing else to corroborate it": "긱 소득을 뒷받침할 다른 자료가 없습니다",
    "A document has no date precise enough to use": "어떤 문서의 날짜가 쓸 수 있을 만큼 정확하지 않습니다",
    "The employment letter is outside the 60-day window": "재직증명서가 60일 기간을 벗어났습니다",
    "This item needs a person to look at it": "이 항목은 사람이 봐야 합니다",
    "Technical details": "기술 세부사항",
    "Code": "코드",
    "Check": "점검",
    "Rule": "규칙",

    // ── app.js: 오류 요약 ───────────────────────────────────────────────────
    "There is one open item on this step": "이 단계에 남은 항목이 하나 있습니다",
    "These are not refusals and nothing is wrong with you. They are the things the system will not settle on its own, listed so a person can settle them.":
      "이것은 거절이 아니며, 당신에게 잘못이 있다는 뜻도 아닙니다. 시스템이 혼자서 결론 내지 않기로 한 것들을, 사람이 결론 낼 수 있도록 적어 둔 것입니다.",
    "One thing on this step needs a person to look at it": "이 단계에서 사람이 봐야 할 것이 하나 있습니다",

    // ── app.js: 문서 화면 ───────────────────────────────────────────────────
    "This household has no documents in this report.": "이 보고서에는 이 세대의 서류가 없습니다.",
    "Documents in this household": "이 세대의 서류",
    "Documents": "서류",
    "application summary": "신청 요약서",
    "pay stub": "급여명세서",
    "employment letter": "재직증명서",
    "gig statement": "긱 수입 명세서",
    "File": "파일",
    "Document date": "문서 날짜",
    "not stated": "적혀 있지 않음",
    "no date": "날짜 없음",
    "Currency": "유효 기간",
    "Read via": "읽은 방법",
    "text layer": "텍스트 레이어",
    "Page size": "페이지 크기",
    "The 60-day window cannot be applied — the date is not precise enough to use without inventing a day.":
      "60일 기간을 적용할 수 없습니다 — 날짜를 지어내지 않고는 쓸 만큼 정확하지 않습니다.",
    "Field": "항목",
    "Value": "값",
    "How we got it": "어떻게 얻었는지",
    "Certainty": "확실도",
    "Text on the page": "문서상의 글자",
    "Page": "페이지",
    "Box (pt)": "영역 (pt)",
    "no box": "영역 없음",
    "Boxes are in PDF points, bottom-left origin, as [x0, y0, x1, y1].":
      "영역은 PDF 포인트 단위이며, 좌하단이 원점인 [x0, y0, x1, y1] 형식입니다.",
    "Page 1 as rendered by the server. Each rectangle is the box the value was read from; the same coordinates are listed as text in the table below.":
      "서버가 그린 1페이지입니다. 각 사각형은 값을 읽어낸 영역이고, 같은 좌표가 아래 표에 글자로 적혀 있습니다.",
    "Loading the page image…": "페이지 이미지를 불러오는 중…",
    "No server is running, so the scanned page cannot be rasterised.":
      "서버가 떠 있지 않아 스캔한 페이지를 이미지로 만들 수 없습니다.",
    "This is a schematic, not the document:": "이것은 문서가 아니라 개략도입니다:",
    "each rectangle is at the real extracted coordinates and holds the real source text, drawn with the same bottom-left-origin conversion the server uses. Exact coordinates are in the table below.":
      "각 사각형은 실제로 추출된 좌표에 놓여 있고 실제 원문 글자를 담고 있으며, 서버가 쓰는 것과 같은 좌하단 원점 변환으로 그려졌습니다. 정확한 좌표는 아래 표에 있습니다.",

    // ── app.js: 정정 화면 ───────────────────────────────────────────────────
    "Your correction is recorded, and it may still not be used": "정정은 기록되지만, 그래도 쓰이지 않을 수 있습니다",
    "A correction changes what the file says. It does not automatically change the annualized amount: if the corrected figure no longer agrees with the hours and rate printed on the same document, that document stops settling what the recurring pay is, and the system says so instead of quietly using the new number.":
      "정정은 파일에 적힌 내용을 바꿉니다. 그렇다고 연환산 금액이 자동으로 바뀌지는 않습니다. 정정한 숫자가 같은 문서에 인쇄된 근무시간·시급과 더 이상 맞지 않으면, 그 문서는 정기 급여가 얼마인지를 확정해 주지 못하게 됩니다. 이때 시스템은 새 숫자를 조용히 쓰지 않고 그 사실을 말합니다.",
    "Recorded corrections available offline": "오프라인에서 쓸 수 있는 기록된 정정",
    "Without a server the app can only replay corrections the pipeline actually ran. Both of these are real pipeline output. Point the app at the API to edit any field.":
      "서버가 없으면 이 앱은 파이프라인이 실제로 실행한 정정만 재생할 수 있습니다. 아래 둘 다 실제 파이프라인 출력입니다. 아무 항목이나 고치려면 앱을 API 에 연결하세요.",
    "Household size is 3, not 1 (application summary)": "세대원 수는 1명이 아니라 3명입니다 (신청 요약서)",
    "Gross pay on the newer stub is $2,500.00, not $2,166.00":
      "더 최근 명세서의 총 급여는 $2,166.00 이 아니라 $2,500.00 입니다",
    "Document": "문서",
    "Field to correct": "정정할 항목",
    "Corrected value": "정정한 값",
    "Type the value as it should read.": "값이 어떻게 적혀야 하는지 그대로 입력하세요.",
    "Apply correction": "정정 반영",
    "Undo correction": "정정 취소",
    "Not available without the server": "서버 없이는 할 수 없습니다",
    "Your correction was recorded and was NOT used": "정정은 기록되었고, 계산에는 쓰이지 않았습니다",
    "Your correction was used": "정정이 쓰였습니다",
    "Why the number did not move": "숫자가 움직이지 않은 이유",
    "This is the honest case, and it is the one that matters: the system kept your correction on the record, refused to fold it into the annualized amount, and said exactly why. The reason is set out under":
      "이것이 정직한 경우이고, 중요한 경우입니다. 시스템은 정정을 기록에 남기고, 그것을 연환산 금액에 반영하기를 거부했으며, 그 이유를 정확히 밝혔습니다. 그 이유는 아래",
    "“Open items on this step”": "“이 단계에 남은 항목”",
    "below, in the system's own words.": "에 시스템 자신의 말로 적혀 있습니다.",
    "The corrected value flowed into the calculation below. Nothing was hidden and no eligibility outcome follows from it.":
      "정정한 값이 아래 계산에 반영되었습니다. 숨긴 것은 없으며, 여기서 자격에 대한 어떤 결론도 따라 나오지 않습니다.",
    "Before and after your correction": "정정 전과 후",
    "Before": "전",
    "After": "후",
    "Corrected field": "정정한 항목",
    "Annualized income": "연환산 소득",
    "Formula": "계산식",
    "Frozen 60% threshold": "동결된 60% 기준액",
    "Comparison": "비교",
    "Readiness": "준비도",
    "Open questions": "남은 물음",
    "(changed)": "(바뀜)",
    "(unchanged)": "(그대로)",
    "below or equal": "이하",
    "above": "초과",
    "no frozen threshold": "동결된 기준액 없음",
    "The threshold moves when household size changes because the frozen HUD table is indexed by household size (rule HUD-MTSP-002). The amount moves only when the recurring base changes.":
      "동결된 HUD 표가 세대원 수로 색인되어 있기 때문에(규칙 HUD-MTSP-002), 세대원 수가 바뀌면 기준액이 움직입니다. 금액은 정기 급여의 기준이 바뀔 때만 움직입니다.",

    // ── app.js: 규칙 질문 화면 ─────────────────────────────────────────────
    "Ask about a rule": "규칙에 대해 물어보기",
    "Routed to deterministic rule handlers. No document text reaches the calculation.":
      "결정론적 규칙 처리기로 넘어갑니다. 문서의 글자는 계산에 도달하지 않습니다.",
    "Ask": "묻기",
    "Recorded questions": "기록된 질문",
    "No recorded answer for that wording": "그 표현으로 기록된 답변이 없습니다",
    "Offline, this app can only replay questions the pipeline actually answered. It will not improvise an answer about a housing rule. Choose one of the recorded questions, or start the API for free-form questions.":
      "오프라인에서는 파이프라인이 실제로 답한 질문만 재생할 수 있습니다. 주택 규칙에 대한 답을 지어내지 않습니다. 기록된 질문 중 하나를 고르거나, 자유롭게 묻고 싶으면 API 를 실행하세요.",
    "Refused, on purpose": "의도적으로 거부했습니다",
    "Abstained — no answer given": "기권했습니다 — 답을 내지 않았습니다",
    "Answer": "답변",
    "No answer is given for this question.": "이 질문에는 답을 내지 않습니다.",
    "What would resolve it:": "무엇이 있으면 풀리는지:",
    "Response kind:": "응답 종류:",
    "Citations": "인용",
    "Citations: none": "인용: 없음",
    "No rule is cited because no rule claim was made. An uncited claim would be the thing this product exists to avoid.":
      "규칙에 대한 주장을 하지 않았으므로 인용할 규칙도 없습니다. 인용 없는 주장이야말로 이 제품이 피하려고 존재하는 것입니다.",
    "Authority": "근거 기관",
    "Effective date": "시행일",
    "Where it says so": "어디에 그렇게 적혀 있는지",
    "Source": "출처",
    "(opens in a new tab)": "(새 탭에서 열림)",
    "Re-checked against the live source": "원문을 다시 대조했는지",
    "Yes": "예",
    "No": "아니오",
    "Not checked — reported as unchecked rather than assumed":
      "확인하지 않음 — 확인한 척하지 않고 확인하지 않았다고 적습니다",

    // ── 서버(api/ask.py, api/plain.py)에서 오는 문장 ────────────────────────
    // 여기가 가장 조심스러운 구역이다. 이 문장들은 시스템이 "나는 자격을 판정하지
    // 않는다"고 말하는 문장이다. 번역이 어설프면 판정하는 것처럼 읽힌다.
    "This service reports readiness only. A qualified housing professional makes the eligibility determination.":
      "이 서비스는 준비도만 보고합니다. 자격 판정은 자격을 갖춘 주택 전문가가 합니다.",
    "This is not an eligibility determination. A qualified housing professional must decide.":
      "이것은 자격 판정이 아닙니다. 자격을 갖춘 주택 전문가가 판단해야 합니다.",
    "That text was treated as document content, not as an instruction. It did not change anything: the readiness calculations are deterministic code and no text from a document or question reaches them.":
      "그 문장은 지시가 아니라 문서의 내용으로 취급했습니다. 그래서 아무것도 바뀌지 않았습니다. 준비도 계산은 결정론적 코드이고, 문서나 질문에 적힌 어떤 글자도 그 계산에 닿지 않습니다.",
    "This session can only answer about its own household. Information about another applicant is never disclosed.":
      "이 세션은 자기 세대에 대해서만 답할 수 있습니다. 다른 신청자의 정보는 어떤 경우에도 공개하지 않습니다.",
    "This service does not determine eligibility and will not label any person. What it reports instead is a readiness status — READY_TO_REVIEW or NEEDS_REVIEW — with the reasons behind it, the annualized amount computed from the documents, the frozen threshold for the household size, and the comparison between those two numbers. Those are statements about paperwork and arithmetic, not about a person. The determination itself is the human handoff: a qualified housing professional makes it, and this service hands them a packet rather than a conclusion. There is no path in this code that returns any other status; the two above are the whole frozen set.":
      "이 서비스는 자격을 판정하지 않으며, 어떤 사람에게도 딱지를 붙이지 않습니다. 대신 보고하는 것은 준비도 상태 — READY_TO_REVIEW 또는 NEEDS_REVIEW — 와 그렇게 본 이유들, 서류에서 계산한 연환산 금액, 그 세대원 수에 대한 동결된 기준액, 그리고 그 두 숫자의 비교입니다. 이것들은 서류와 산술에 대한 진술이지 사람에 대한 진술이 아닙니다. 판정 자체는 사람에게 넘기는 일입니다. 자격을 갖춘 주택 전문가가 판정하고, 이 서비스는 결론이 아니라 서류 묶음을 건넵니다. 이 코드에는 다른 상태를 돌려주는 경로가 없습니다. 위의 둘이 동결된 전부입니다.",
    "ask what the frozen threshold is, what the annualized amount is, how the two compare, or what is still missing or expired":
      "동결된 기준액이 얼마인지, 연환산 금액이 얼마인지, 그 둘이 어떻게 비교되는지, 또는 아직 무엇이 없거나 기한이 지났는지를 물어보세요",
    "open that household's own session, with that renter's consent":
      "그 세입자의 동의를 받아, 해당 세대 자신의 세션을 여세요",
    "ask about a rule, a required document, or a calculation instead":
      "대신 규칙이나 필요한 서류, 또는 계산에 대해 물어보세요",
    "the renter or employer confirms whether the extra pay recurs":
      "세입자 또는 고용주가 그 추가 급여가 반복되는지 확인해 주면 됩니다",
    "the renter also corrects regular_hours or hourly_rate on that document so the three figures agree, or the renter or employer confirms which document reflects recurring pay":
      "세입자가 그 문서의 regular_hours 또는 hourly_rate 도 함께 고쳐 세 숫자가 맞아떨어지게 하거나, 세입자 또는 고용주가 어느 문서가 정기 급여를 나타내는지 확인해 주면 됩니다",
    "the renter uploads platform earnings records, bank deposits, or a 1099 covering the same period":
      "세입자가 같은 기간을 포함하는 플랫폼 수입 기록, 은행 입금 내역, 또는 1099 를 올리면 됩니다",
    "the renter uploads the missing document": "세입자가 빠진 서류를 올리면 됩니다",
    "the renter supplies a day-precise statement or confirms the date":
      "세입자가 일(日)까지 적힌 명세서를 내거나 날짜를 확인해 주면 됩니다",
    "the renter uploads a document dated on or after 2026-05-19":
      "세입자가 2026-05-19 이후 날짜의 서류를 올리면 됩니다",

    // 체크리스트 항목 이름과 세입자가 할 일 (서버 데이터이지만 고정 문자열이다)
    "Application summary": "신청 요약서",
    "Recent pay stubs": "최근 급여명세서",
    "Employment verification letter": "재직증명서",
    "Independent corroboration of gig income": "긱 소득을 뒷받침하는 독립 자료",
    "Gig platform earnings statement": "긱 플랫폼 수입 명세서",
    "Ask your employer for a signed employment verification letter":
      "고용주에게 서명된 재직증명서를 요청하세요",
    "Upload bank deposits, platform earnings records, or a 1099 covering the same period":
      "같은 기간을 포함하는 은행 입금 내역, 플랫폼 수입 기록, 또는 1099 를 올리세요",
    "Upload your most recent gig platform earnings statement":
      "가장 최근의 긱 플랫폼 수입 명세서를 올리세요",

    // ── app.js: 계산 화면 ───────────────────────────────────────────────────
    "Ruleset": "규칙 묶음",
    "Frozen event date": "동결된 기준 날짜",
    "Engine": "엔진",
    "Input": "입력값",
    "From document": "출처 문서",
    "annualized income": "연환산 소득",
    "annualized wage income": "연환산 임금 소득",
    // 계산의 입력 이름. 항목 id(gross_pay)가 아니라 사람이 읽는 이름이라 옮긴다.
    "gross pay": "총 급여",
    "pay frequency": "급여 주기",
    "corroborating weekly hours x rate": "주당 근무시간 × 시급으로 교차 확인",
    "Result": "결과",
    "No threshold applies to this line": "이 줄에 적용되는 기준액이 없습니다",
    "Threshold rule": "기준액 규칙",
    "Calculation rule": "계산 규칙",
    "Rules cited by this report": "이 보고서가 인용한 규칙",

    // ── app.js: 점검표 화면 ────────────────────────────────────────────────
    "readiness_status": "readiness_status",
    "What you can do next": "다음에 할 수 있는 일",
    "Item": "항목",
    "Required because": "필요한 이유",
    "Satisfied by": "무엇으로 충족되었는지",
    "nothing yet": "아직 없음",
    "Detail": "세부 내용",
    "What you can do": "할 수 있는 일",
    "Nothing — this one is done.": "없음 — 이 항목은 끝났습니다.",

    // ── app.js: 확인 화면과 서류 묶음 ───────────────────────────────────────
    "Change": "변경",
    "Values read from the documents": "서류에서 읽은 값",
    "Your corrections": "내 정정",
    "You have not corrected anything.": "아직 아무것도 정정하지 않았습니다.",
    "Rule you asked about": "물어본 규칙",
    "You have not asked about a rule.": "아직 규칙에 대해 묻지 않았습니다.",
    "Yearly income figure": "연 소득 금액",
    "No income calculation is present in this report.": "이 보고서에는 소득 계산이 없습니다.",
    "Still missing or out of date": "아직 없거나 기한이 지난 것",
    "Nothing. Every required item is present and current.":
      "없습니다. 필요한 항목이 모두 있고 유효합니다.",
    "Questions the system will not answer on its own": "시스템이 혼자서 답하지 않는 물음",
    "the household documents we read": "우리가 읽은 세대 서류",
    "the values we read from your documents": "서류에서 읽은 값들",
    "the correction you made to a value we read": "읽어낸 값에 대해 한 정정",
    "the housing rule you asked about": "물어본 주택 규칙",
    "how the yearly income figure was worked out": "연 소득 금액이 산출된 방법",
    "what is missing or out of date": "없거나 기한이 지난 것",
    "Take your packet": "서류 묶음 받기",
    "Nothing is sent anywhere.": "어디로도 전송되지 않습니다.",
    "This button writes a file to your own device and nothing else. RealDoor does not transmit your packet to any property, provider, or third party — sharing it is your decision, made outside this app.":
      "이 버튼은 당신의 기기에 파일 하나를 쓸 뿐입니다. RealDoor 는 서류 묶음을 어떤 임대인·기관·제3자에게도 보내지 않습니다. 공유할지 말지는 이 앱 바깥에서 당신이 정합니다.",
    "The packet contains what your documents show, what is still missing or expired, and every open question below. It contains no eligibility outcome, because this service does not produce one.":
      "서류 묶음에는 당신의 서류가 보여주는 것, 아직 없거나 기한이 지난 것, 그리고 아래의 모든 남은 물음이 담깁니다. 자격에 대한 결론은 담기지 않습니다. 이 서비스가 그런 결론을 만들지 않기 때문입니다.",
    "Download my readiness packet": "내 준비도 서류 묶음 내려받기",

    // ── app.js: 통제 시연 화면 ─────────────────────────────────────────────
    "Someone demands an eligibility decision": "누군가 자격 판정을 요구할 때",
    "Someone asks about a different applicant": "누군가 다른 신청자에 대해 물을 때",
    "A document tries to give the system instructions": "문서가 시스템에 지시를 내리려 할 때",
    "Input:": "입력:",
    "Run this probe": "이 시험 실행",
    "Response returned": "돌아온 응답",
    "Offered instead:": "대신 제안한 것:",
    "The output gate, tested against itself": "출력 차단 장치를 자기 자신에게 시험하기",
    "The server has an endpoint whose only job is to try to return a forbidden payload — one containing an eligibility flag and a numeric rating. If the gate is working, that response never reaches you: the server withholds its own answer and returns HTTP 500 instead. This endpoint succeeding would be the system failing.":
      "서버에는 금지된 응답 — 자격 플래그와 숫자 등급이 들어 있는 응답 — 을 돌려주려고 시도하는 것만이 유일한 일인 엔드포인트가 있습니다. 차단 장치가 작동한다면 그 응답은 당신에게 결코 도달하지 않습니다. 서버가 자기 답을 스스로 막고 대신 HTTP 500 을 돌려주기 때문입니다. 이 엔드포인트가 성공하는 것이 곧 시스템의 실패입니다.",
    "Try to make the server return a decision": "서버가 판정을 돌려주게 만들어 보기",
    "Not run — there is no server to test": "실행하지 않음 — 시험할 서버가 없습니다",
    "This control lives in the API process, so it cannot be demonstrated from bundled fixtures. Rather than show you a recording and call it a live test, the app reports it as not run. Start the API and set window.REALDOOR_API to see the real 500.":
      "이 통제는 API 프로세스 안에 있어서 번들된 고정 데이터만으로는 시연할 수 없습니다. 녹화된 것을 보여주면서 실시간 시험이라고 부르는 대신, 앱은 실행하지 않았다고 보고합니다. 실제 500 을 보려면 API 를 실행하고 window.REALDOOR_API 를 설정하세요.",
    "Delete this session": "이 세션 삭제",
    "Everything this app holds about the household lives in one session. Deleting it removes the documents, the extracted values, and every correction from the process; requests that follow return 404 because there is nothing left to answer with.":
      "이 앱이 그 세대에 대해 갖고 있는 모든 것은 하나의 세션 안에 있습니다. 세션을 지우면 서류, 추출된 값, 모든 정정이 프로세스에서 사라집니다. 이후의 요청은 404 를 돌려받습니다 — 답할 거리가 남아 있지 않기 때문입니다.",
    "Delete session data now": "지금 세션 데이터 삭제",
    "In-page session data cleared": "화면 안의 세션 데이터를 지웠습니다",
    "Offline there is no server session to destroy, so this clears everything the page was holding: the report, the correction, and the selected document. Reload the page to start again. With the API connected, this same button deletes the server session.":
      "오프라인에서는 없앨 서버 세션이 없으므로, 이 동작은 화면이 들고 있던 모든 것 — 보고서, 정정, 선택한 문서 — 을 지웁니다. 다시 시작하려면 화면을 새로 고치세요. API 에 연결되어 있으면 같은 버튼이 서버 세션을 삭제합니다.",
    "Server session deleted": "서버 세션을 삭제했습니다",

    // ── app.js: 우리 성적표 ────────────────────────────────────────────────
    "Reading values off the documents": "서류에서 값 읽어내기",
    "Hostile inputs from the challenge pack": "과제 팩의 적대적 입력",
    "Agreement with the organizer's own calculator": "주최 측 자체 계산기와의 일치",
    "Rule questions answered correctly": "규칙 질문에 올바로 답한 비율",
    "Citations re-checked against their live source": "인용을 원문과 다시 대조한 결과",
    "Accessibility scan": "접근성 검사",
    "Measurements are loading…": "측정값을 불러오는 중…",
    "Not run": "실행 안 함",
    "Measured": "측정함",
    "Measure": "측정 항목",
    "none": "없음",
    "About the numbers that look bad": "나빠 보이는 숫자에 대하여",
    "Every number here is produced by re-running the measurement, not copied from a previous run. Sections that cannot be measured are marked not_run rather than filled in.":
      "여기의 모든 숫자는 측정을 다시 돌려서 나온 것이지, 이전 실행에서 베껴온 것이 아닙니다. 측정할 수 없는 항목은 채워 넣지 않고 not_run 으로 표시합니다.",
    "Abstentions are counted separately and are never scored as wrong answers.":
      "기권은 따로 세며, 틀린 답으로 채점하지 않습니다.",
    "The pack's 24 tests are 12 distinct hostile inputs, each present twice. We report 24 runs but only 12 independent probes. Detectors are keyword and canary based: a pass is evidence, not proof.":
      "팩의 24개 시험은 서로 다른 적대적 입력 12개가 각각 두 번씩 들어 있는 것입니다. 우리는 24회 실행을 보고하지만 독립적인 시험은 12개뿐입니다. 탐지기는 키워드와 카나리아 기반입니다. 통과는 증거이지 증명이 아닙니다.",
    "Compared against pack/starter/src/calculate.py, the organizer's own reference implementation, imported directly rather than copied.":
      "주최 측 자체 참조 구현인 pack/starter/src/calculate.py 와 대조했습니다. 베끼지 않고 직접 import 했습니다.",
    "Re-verifying each cited rule against its live source URL is not wired yet. Reported as zero rather than assumed.":
      "인용한 각 규칙을 원문 URL 과 다시 대조하는 작업은 아직 연결되어 있지 않습니다. 됐다고 가정하지 않고 0 으로 보고합니다.",
    "Incomplete means axe declined to judge, not that a check passed. Both file:// and http:// origins are scanned because a local file cannot read the stylesheet, which makes colour contrast unknowable rather than fine.":
      "incomplete 는 검사를 통과했다는 뜻이 아니라 axe 가 판단을 보류했다는 뜻입니다. 로컬 파일은 스타일시트를 읽을 수 없어 색 대비를 알 수 없게 되므로, file:// 과 http:// 두 출처를 모두 검사합니다.",
    "The accessibility row reads not_run because this interface did not exist when that snapshot was taken. The scan has since been run against every screen of this build, over both file:// and http://; its raw output is written to ui/axe-report.json. It is not restated here, because this panel shows the measurement file as it is, not as we would like it to read.":
      "접근성 줄이 not_run 인 것은 그 스냅숏을 찍을 때 이 화면이 아직 없었기 때문입니다. 그 뒤로 이 빌드의 모든 화면에 대해 file:// 과 http:// 양쪽에서 검사를 돌렸고, 원본 출력은 ui/axe-report.json 에 기록되어 있습니다. 여기에 다시 적지 않는 이유는, 이 칸이 측정 파일을 우리가 바라는 모습이 아니라 있는 그대로 보여주기 때문입니다.",

    // ── app.js: 남은 물음 레일 ─────────────────────────────────────────────
    "No report is loaded.": "불러온 보고서가 없습니다.",
    "None for this household: every value needed was read from a document and every required item is accounted for. An empty list means nothing was withheld, not that nothing was checked.":
      "이 세대에는 없습니다. 필요한 값은 모두 문서에서 읽었고 필요한 항목도 모두 확인되었습니다. 목록이 비어 있다는 것은 아무것도 숨기지 않았다는 뜻이지, 아무것도 확인하지 않았다는 뜻이 아닙니다.",
    "None recorded for this household.": "이 세대에 기록된 것이 없습니다.",

    // ── app.js: 오류 카드와 빈 상태 ────────────────────────────────────────
    "No report is loaded for this household": "이 세대에 불러온 보고서가 없습니다",
    "The offline bundle carries the pipeline's real output for HH-001, HH-004 and HH-005 only. The other households exist in the file list but no report was exported for them, and the app will not fabricate one. Start the API and set window.REALDOOR_API to load any household.":
      "오프라인 번들에는 HH-001, HH-004, HH-005 의 실제 파이프라인 출력만 들어 있습니다. 다른 세대는 파일 목록에는 있지만 보고서가 내보내지지 않았고, 앱은 그것을 지어내지 않습니다. 아무 세대나 불러오려면 API 를 실행하고 window.REALDOOR_API 를 설정하세요.",
    "The correction could not be applied": "정정을 반영할 수 없었습니다",
    "The question could not be sent": "질문을 보낼 수 없었습니다",
    "The probe could not be run": "시험을 실행할 수 없었습니다",
    "The session could not be deleted": "세션을 삭제할 수 없었습니다",
    "The packet could not be built": "서류 묶음을 만들 수 없었습니다",
    "Measurements could not be loaded": "측정값을 불러올 수 없었습니다",
    "Households could not be loaded": "세대 목록을 불러올 수 없었습니다",

    // ── app.js: 데이터 출처 설명 ───────────────────────────────────────────
    "Bundled fixtures — real pipeline output, no server, no network":
      "번들된 고정 데이터 — 실제 파이프라인 출력, 서버 없음, 네트워크 없음",

    // ── app.js: 스크린리더 알림 (announce) 중 고정 문구 ─────────────────────
    "Cleared the highlight": "강조를 껐습니다",
    "There is no correction to undo.": "취소할 정정이 없습니다.",
    "Correction undone. The report is back to the extracted values.":
      "정정을 취소했습니다. 보고서가 추출된 값으로 돌아갔습니다.",
    "Enter a corrected value first.": "먼저 정정한 값을 입력하세요.",
    "That correction is not available offline.": "그 정정은 오프라인에서 쓸 수 없습니다.",
    "Correction recorded, but it was not used in the calculation. See the explanation.":
      "정정을 기록했지만 계산에는 쓰지 않았습니다. 설명을 보세요.",
    "Correction applied. The downstream numbers have been recomputed.":
      "정정을 반영했습니다. 이후의 숫자들을 다시 계산했습니다.",
    "Gate self-test not run: no server is connected.":
      "차단 장치 자체 시험을 실행하지 않았습니다: 연결된 서버가 없습니다.",
    "Gate held. The server withheld its own response with HTTP 500.":
      "차단 장치가 버텼습니다. 서버가 HTTP 500 으로 자기 응답을 스스로 막았습니다.",
    "Gate failed. A forbidden payload got through.":
      "차단 장치가 뚫렸습니다. 금지된 응답이 빠져나갔습니다.",
    "Session data cleared from this page.": "이 화면에서 세션 데이터를 지웠습니다.",
    "Server session deleted.": "서버 세션을 삭제했습니다.",

    // ── 언어 토글 자체 ─────────────────────────────────────────────────────
    "currently English — activate for Korean": "현재 영어 — 누르면 한국어로 바뀝니다"
  };

  // ── 규칙: 숫자나 식별자가 끼어들어 사전으로는 못 잡는 문장 ──────────────────
  // 각 항목은 [정규식, 한국어를 만드는 함수]. 함수는 잡힌 그룹을 받는다. 데이터
  // (금액·날짜·세대 id·항목 이름)는 절대 번역하지 않고 그대로 끼워 넣는다.
  var RULES = [
    // 진행 안내와 이동
    [/^Step (\d+) of 6\.\s*(.*)$/, function (m) {
      return "6단계 중 " + m[1] + "단계. " + (lookup(m[2]) || m[2]);
    }],
    [/^Back to step (\d+)$/, function (m) { return m[1] + "단계로 돌아가기"; }],
    [/^Continue to step (\d+)$/, function (m) { return m[1] + "단계로 계속"; }],
    [/^Go to step (\d+)$/, function (m) { return m[1] + "단계로 가기"; }],
    // 조회 전에 공백을 접고 잘라내므로, 키에는 앞뒤 공백을 넣지 않는다.
    // 원래 붙어 있던 공백은 노드에 다시 쓸 때 그대로 복원된다.
    [/^to see this item in context$/, function () { return "— 이 항목을 맥락 속에서 보기"; }],

    // 남은 항목 개수
    [/^There are (\d+) open items on this step$/, function (m) {
      return "이 단계에 남은 항목이 " + m[1] + "개 있습니다";
    }],
    [/^(\d+) things on this step need a person to look at them$/, function (m) {
      return "이 단계에서 사람이 봐야 할 것이 " + m[1] + "개 있습니다";
    }],
    [/^The remaining (\d+) open item\(s\) are listed in full below\.$/, function (m) {
      return "남은 " + m[1] + "개 항목은 아래에 전부 나열되어 있습니다.";
    }],
    // 한 항목이 여러 건을 대표할 때, 위의 개수와 어긋나 보이지 않도록 그 사실을 말한다.
    [/^Counted above as (\d+) entries\. They are the same item, and each one is kept in full under Technical details\.$/,
      function (m) {
        return "위 개수에는 " + m[1] + "건으로 잡혀 있습니다. 같은 항목이며, 각 건은 " +
               "기술 세부정보에 그대로 보관되어 있습니다.";
      }],
    [/^(\d+) separate checks raised this one item\. Each check is listed in full under Technical details\.$/,
      function (m) {
        return "서로 다른 검사 " + m[1] + "건이 이 한 항목을 제기했습니다. 각 검사는 " +
               "기술 세부정보에 전부 나열되어 있습니다.";
      }],
    [/^Abstentions \((\d+)\)$/, function (m) { return "기권 (" + m[1] + ")"; }],
    [/^Reasons this needs review \((\d+)\)$/, function (m) {
      return "검토가 필요한 이유 (" + m[1] + ")";
    }],
    // 점검표 구역 제목: "Missing (2)" 처럼 상태어 + 개수
    [/^(Present|Missing|Expired|Undatable|Unreadable) \((\d+)\)$/, function (m) {
      return DICT[m[1]] + " (" + m[2] + ")";
    }],

    // 문서 유효 기간
    [/^Outside the 60-day window by (\d+) day\(s\)\.$/, function (m) {
      return "60일 기간을 " + m[1] + "일 넘겼습니다.";
    }],
    [/^(\d+) day\(s\) of the 60-day window remaining\.$/, function (m) {
      return "60일 기간 중 " + m[1] + "일 남았습니다.";
    }],

    // 표 캡션과 제목
    [/^Extracted values on (\S+)\. Choose a field name to highlight its box on the page\.$/, function (m) {
      return m[1] + " 에서 추출한 값입니다. 항목 이름을 고르면 문서상의 영역이 강조됩니다.";
    }],
    [/^Inputs to (.+)$/, function (m) { return (lookup(m[1]) || m[1]) + " 의 입력값"; }],
    [/^Measurements for (.+)$/, function (m) { return (lookup(m[1]) || m[1]) + " 측정값"; }],
    [/^Measured at (.+)\.$/, function (m) { return m[1] + " 에 측정함."; }],

    // 데이터 출처 줄 (엔진 sha·ruleset 은 빌드 메타데이터라 손대지 않는다)
    [/^Data source: (.+)$/, function (m) { return "데이터 출처: " + (lookup(m[1]) || m[1]); }],
    // 주소 부분은 데이터라 그대로 두되, apiBase 가 빈 문자열일 때 app.js 가 넣는
    // "this origin" 은 주소가 아니라 문장이므로 옮긴다.
    [/^Live API at (.+) \(same shapes as the fixtures\)$/, function (m) {
      return (m[1] === "this origin" ? "이 출처" : m[1]) + " 의 실시간 API (고정 데이터와 같은 형태)";
    }],

    // 세대 선택과 확인 화면
    [/^(HH-\d+) — (\d+) documents$/, function (m) { return m[1] + " — 서류 " + m[2] + "건"; }],
    [/^(HH-\d+) — (\d+) documents \(no bundled report\)$/, function (m) {
      return m[1] + " — 서류 " + m[2] + "건 (번들된 보고서 없음)";
    }],
    [/^(HH-\d+) · (\d+) documents$/, function (m) { return m[1] + " · 서류 " + m[2] + "건"; }],
    [/^(\d+) values, each one traced to a box on a page$/, function (m) {
      return "값 " + m[1] + "개. 각각이 문서상의 한 영역까지 추적됩니다";
    }],
    [/^(\d+) item\(s\): (.+)$/, function (m) {
      return m[1] + "개 항목: " + m[2].split(", ").map(function (label) {
        return lookup(label) || label;
      }).join(", ");
    }],
    [/^(\d+) abstention\(s\) and (\d+) reason\(s\) this needs review\. All of them are listed in full under “What this system is unsure about”, and all of them travel with your packet\.$/,
      function (m) {
        return "기권 " + m[1] + "건과 검토가 필요한 이유 " + m[2] + "건. 모두 “이 시스템이 확신하지 못하는 것”" +
               "아래에 빠짐없이 나열되어 있으며, 모두 서류 묶음에 함께 실립니다.";
      }],
    [/^(.+) = (.+) on (\S+) — recorded, but not used in the calculation$/, function (m) {
      return m[1] + " = " + m[2] + " (" + m[3] + ") — 기록했지만 계산에는 쓰지 않았습니다";
    }],
    [/^(.+) = (.+) on (\S+) — used in the calculation$/, function (m) {
      return m[1] + " = " + m[2] + " (" + m[3] + ") — 계산에 썼습니다";
    }],
    [/^(.+) = (.+) on (\S+)$/, function (m) { return m[1] + " = " + m[2] + " (" + m[3] + ")"; }],

    // 결과 금액 + 비교 문장
    [/^(\$[\d,.]+) — (.+)$/, function (m) { return m[1] + " — " + (lookup(m[2]) || m[2]); }],

    // 문서 상세 제목: "<문서 종류> — <문서 id>". id 는 기계 식별자라 그대로 둔다.
    [/^(.+) — (HH-\d+-D\d+)$/, function (m) { return (lookup(m[1]) || m[1]) + " — " + m[2]; }],
    // 같은 짝의 반대 순서 — 정정 양식의 문서 선택 항목.
    [/^(HH-\d+-D\d+) — (.+)$/, function (m) { return m[1] + " — " + (lookup(m[2]) || m[2]); }],
    // 정정할 항목 선택: "<항목 id> (currently <값>)". id 와 값은 둘 다 데이터다.
    [/^(\S+) \(currently (.+)\)$/, function (m) { return m[1] + " (현재 " + m[2] + ")"; }],

    // 물어본 질문을 그대로 되비추는 줄. 질문 자체는 사용자/팩의 원문이므로 번역하지 않는다.
    [/^Question asked: (.+)$/, function (m) { return "물어본 질문: " + m[1]; }],

    // 차단 장치 결과
    [/^Gate held\. HTTP (\d+) — the server withheld its own response\.$/, function (m) {
      return "차단 장치가 버텼습니다. HTTP " + m[1] + " — 서버가 자기 응답을 스스로 막았습니다.";
    }],
    [/^GATE FAILED\. HTTP (\d+) — a forbidden payload got through\.$/, function (m) {
      return "차단 장치가 뚫렸습니다. HTTP " + m[1] + " — 금지된 응답이 빠져나갔습니다.";
    }],
    [/^Session (\S+) no longer exists in the API process\. Any further request with that id returns 404\.$/, function (m) {
      return "세션 " + m[1] + " 은 API 프로세스에 더 이상 존재하지 않습니다. 그 id 로 보내는 이후 요청은 404 를 돌려받습니다.";
    }],

    // 서류 묶음 내려받기
    [/^Downloaded (\S+) to your device at your request\. No network transmission took place\.$/, function (m) {
      return m[1] + " 을 요청하신 대로 기기에 내려받았습니다. 네트워크 전송은 일어나지 않았습니다.";
    }],
    [/^Packet (\S+) downloaded to your device\. Nothing was sent anywhere\.$/, function (m) {
      return "서류 묶음 " + m[1] + " 을 기기에 내려받았습니다. 어디로도 전송되지 않았습니다.";
    }],

    // 오프라인 정정 불가 안내
    [/^This build is running on bundled fixtures, which contain only the two corrections the pipeline actually ran\. Rather than invent a result for (.+), the app declines to show one\. Start the API and set window\.REALDOOR_API to correct any field\.$/,
      function (m) {
        return "이 빌드는 번들된 고정 데이터로 돌아가고 있고, 거기에는 파이프라인이 실제로 실행한 정정 두 건만 들어 있습니다. " +
               m[1] + " 에 대한 결과를 지어내는 대신, 앱은 보여주기를 거부합니다. 아무 항목이나 정정하려면 API 를 실행하고 window.REALDOOR_API 를 설정하세요.";
      }],

    // 스크린리더 알림
    [/^Showing document (\S+), (.+)$/, function (m) {
      return "문서 " + m[1] + " 을 표시합니다. " + (lookup(m[2]) || m[2]);
    }],
    [/^Highlighted (\S+) on page (\d+)$/, function (m) {
      return m[1] + " 을 " + m[2] + "페이지에서 강조했습니다";
    }],
    [/^Filled the correction form with: (.+)$/, function (m) {
      return "정정 양식을 다음으로 채웠습니다: " + (lookup(m[1]) || m[1]);
    }],
    [/^Loaded (\S+)\. (.+)$/, function (m) {
      return m[1] + " 을 불러왔습니다. " + (lookup(m[2]) || m[2]);
    }],
    [/^Refused, on purpose\. (.+)$/, function (m) {
      return "의도적으로 거부했습니다. " + (lookup(m[1]) || m[1]);
    }],
    [/^Abstained — no answer given\. (.+)$/, function (m) {
      return "기권했습니다 — 답을 내지 않았습니다. " + (lookup(m[1]) || m[1]);
    }],
    [/^Answer\. (.+)$/, function (m) { return "답변. " + (lookup(m[1]) || m[1]); }],
    [/^(Someone demands an eligibility decision|Someone asks about a different applicant|A document tries to give the system instructions): (.+)$/,
      function (m) { return DICT[m[1]] + ": " + (lookup(m[2]) || m[2]); }],

    // "Resolved by: " + 문장
    [/^Resolved by: (.+)$/, function (m) { return "이렇게 하면 풀립니다: " + (lookup(m[1]) || m[1]); }],

    // "다음에 할 수 있는 일" 목록의 "<항목 이름>: " 접두. 사전이 먼저 조회되므로
    // 이미 사전에 있는 "Input:" 같은 것은 여기까지 오지 않는다. 항목 이름을 모르면
    // null 을 돌려 번역하지 않는다 — 반쪽짜리 한국어를 만드느니 영어로 둔다.
    [/^(.+):$/, function (m) {
      var label = lookup(m[1]);
      return label === null ? null : label + ":";
    }],

    // 페이지 크기 (숫자와 단위는 데이터)
    [/^([\d.]+ × [\d.]+) pt, (\d+) page\(s\)$/, function (m) {
      return m[1] + " pt, " + m[2] + "페이지";
    }],

    // 성적표 하단의 "나빠 보이는 숫자" 문단 — 앞부분만 규칙으로, 항목명은 사전으로.
    [/^No measured section fell short in this run\. (.*)$/, function (m) {
      return "이번 실행에서 기준에 못 미친 측정 항목은 없습니다. " + tailOfShortfallNote(m[1]);
    }],
    [/^Measured shortfalls in this run — (.+?)\. (Not run at all: .+?\. )?(These are the measurements.*)$/,
      function (m) {
        return "이번 실행에서 측정된 미달 항목 — " + m[1] + ". " +
               (m[2] ? "아예 실행하지 않은 항목: " + m[2].replace(/^Not run at all: /, "") : "") +
               tailOfShortfallNote(m[3]);
      }]
  ];

  var SHORTFALL_TAIL =
    "These are the measurements as they came out at the timestamp above. They are printed here " +
    "rather than smoothed, because a product whose whole argument is that quality must be measured " +
    "cannot then publish only its good numbers.";
  var SHORTFALL_TAIL_KO =
    "위 시각에 나온 그대로의 측정값입니다. 다듬지 않고 그대로 싣습니다. 품질은 측정되어야 한다는 " +
    "것이 논지의 전부인 제품이 좋은 숫자만 골라 공개할 수는 없기 때문입니다.";

  function tailOfShortfallNote(rest) {
    var trimmed = String(rest || "").trim();
    // "Not run at all: X, Y. " 가 앞에 붙어 있을 수 있다.
    var notRun = trimmed.match(/^Not run at all: (.+?)\. (.*)$/);
    var prefix = "";
    if (notRun) {
      prefix = "아예 실행하지 않은 항목: " + notRun[1] + ". ";
      trimmed = notRun[2];
    }
    return prefix + (trimmed.indexOf(SHORTFALL_TAIL.slice(0, 40)) === 0 ? SHORTFALL_TAIL_KO : trimmed);
  }

  // ── 통째로 갈아 끼우는 문단 ────────────────────────────────────────────────
  // 대부분의 문장은 텍스트 노드 하나라서 사전으로 잡히지만, 문장 한가운데에
  // <em> 이나 <code> 가 끼어 있으면 한 문장이 세 조각으로 쪼개진다. 조각마다
  // 번역하면 한국어 어순이 무너지므로(영어의 강조 위치와 한국어의 강조 위치가
  // 다르다), 그런 문단만 통째로 다시 만든다. 영어 원본 자식 노드는 그대로 떼어
  // 보관했다가 되돌릴 때 다시 붙인다 — 다시 파싱하지 않으므로 원문이 변형될 수 없다.
  //
  // 값은 조각의 배열이다. 문자열은 그냥 글자, ["em", "..."] 은 <em> 안의 글자.
  // 강조는 영어에서 강조된 것과 같은 의미 단위에 붙인다.
  var BLOCKS = {
    "lede-correct": [
      "시스템이 읽은 값을 바꾸고, 그 아래 숫자들이 따라 움직이는지 보세요. 또는 그 정정이 왜 쓰이지 ",
      ["em", "않았는지"],
      " 시스템이 설명하는 것을 보세요."
    ],
    "footer-privacy": [
      "외부 폰트·스크립트·이미지·분석 도구가 없습니다. 이 화면이 보내는 모든 요청은 위 주소창의 " +
      "주소로만 가고 다른 어디로도 가지 않습니다. 파일로 열면 요청을 아예 보내지 않습니다. " +
      "데이터 출처는 화면 맨 위에 적혀 있고, URL 에 ",
      ["code", "?fixtures"],
      " 를 붙이면 오프라인 출처를 강제할 수 있습니다."
    ]
  };

  var blockOriginals = new WeakMap();   // 요소 → 떼어 둔 영어 자식 노드 배열
  var touchedBlock = [];

  function applyBlock(element) {
    var key = element.getAttribute("data-i18n-block");
    var parts = BLOCKS[key];
    if (!parts || blockOriginals.has(element)) return;
    var saved = Array.prototype.slice.call(element.childNodes);
    blockOriginals.set(element, saved);
    touchedBlock.push(element);
    while (element.firstChild) element.removeChild(element.firstChild);
    parts.forEach(function (part) {
      if (typeof part === "string") {
        element.appendChild(document.createTextNode(part));
        return;
      }
      var wrapper = document.createElement(part[0]);
      wrapper.appendChild(document.createTextNode(part[1]));
      element.appendChild(wrapper);
    });
  }

  function restoreBlocks() {
    touchedBlock.forEach(function (element) {
      var saved = blockOriginals.get(element);
      if (!saved) return;
      while (element.firstChild) element.removeChild(element.firstChild);
      saved.forEach(function (node) { element.appendChild(node); });
      blockOriginals.delete(element);
    });
    touchedBlock = [];
  }

  // ── 조회 ────────────────────────────────────────────────────────────────────
  // 여러 줄에 걸친 HTML 텍스트도 잡히도록 공백을 하나로 접은 뒤 찾는다.
  function normalize(text) { return String(text).replace(/\s+/g, " ").trim(); }

  function lookup(text) {
    var key = normalize(text);
    if (!key) return null;
    if (Object.prototype.hasOwnProperty.call(DICT, key)) return DICT[key];
    for (var i = 0; i < RULES.length; i += 1) {
      var m = key.match(RULES[i][0]);
      if (m) return RULES[i][1](m);
    }
    return null;
  }

  // ── DOM 적용 ────────────────────────────────────────────────────────────────
  // 기계 식별자가 사는 곳은 건드리지 않는다. 규칙 id·필드명·좌표·엔진 sha 는
  // 번역 대상이 아니라 데이터다.
  var SKIP = "script, style, code, .mono, .formula, .box-tag, .schematic-text, #footer-meta";
  var ATTRS = ["aria-label", "alt", "title", "placeholder"];

  var lang = "en";
  var applying = false;
  var textOriginals = new WeakMap();   // 텍스트 노드 → 영어 원문
  var attrOriginals = new WeakMap();   // 요소 → {속성명: 영어 원문}
  var touchedText = [];                // 되돌릴 때 훑기 위한 목록
  var touchedAttr = [];

  function isSkipped(node) {
    var parent = node.parentElement;
    return !parent || parent.closest(SKIP) !== null;
  }

  function applyToTextNode(node) {
    if (isSkipped(node)) return;
    var raw = node.nodeValue;
    if (!raw || !/\S/.test(raw)) return;
    var original = textOriginals.has(node) ? textOriginals.get(node) : raw;
    var ko = lookup(original);
    if (ko === null) return;
    if (!textOriginals.has(node)) {
      textOriginals.set(node, raw);
      touchedText.push(node);
    }
    // 원문의 앞뒤 공백은 그대로 살린다. "Rule " 처럼 뒤 공백이 의미를 갖는 자리가 있다.
    var lead = original.match(/^\s*/)[0];
    var tail = original.match(/\s*$/)[0];
    var next = lead + ko + tail;
    // 같은 값을 다시 써도 characterData 변경으로 기록된다. 이미 번역돼 있으면 손대지 않는다.
    if (node.nodeValue !== next) node.nodeValue = next;
  }

  function applyToAttrs(element) {
    for (var i = 0; i < ATTRS.length; i += 1) {
      var name = ATTRS[i];
      if (!element.hasAttribute(name)) continue;
      var store = attrOriginals.get(element) || {};
      var original = Object.prototype.hasOwnProperty.call(store, name)
        ? store[name] : element.getAttribute(name);
      var ko = lookup(original);
      if (ko === null) continue;
      if (!Object.prototype.hasOwnProperty.call(store, name)) {
        store[name] = original;
        attrOriginals.set(element, store);
        touchedAttr.push({ element: element, name: name });
      }
      if (element.getAttribute(name) !== ko) element.setAttribute(name, ko);
    }
  }

  function walk(root) {
    if (root.nodeType === 3) { applyToTextNode(root); return; }
    if (root.nodeType !== 1) return;
    if (root.matches && root.matches(SKIP)) return;
    applyToAttrs(root);
    // 통째로 가는 문단은 조각 번역을 하지 않는다. 먼저 처리하고 그 안으로는 내려가지 않는다.
    if (root.hasAttribute && root.hasAttribute("data-i18n-block")) { applyBlock(root); return; }
    Array.prototype.forEach.call(
      root.querySelectorAll ? root.querySelectorAll("[data-i18n-block]") : [], applyBlock);
    var iterator = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var pending = [];
    var node;
    while ((node = iterator.nextNode())) pending.push(node);
    pending.forEach(applyToTextNode);
    var elements = root.querySelectorAll ? root.querySelectorAll("[" + ATTRS.join("],[") + "]") : [];
    Array.prototype.forEach.call(elements, applyToAttrs);
  }

  /** 우리가 방금 일으킨 DOM 변경은 옵저버에게 전달되기 전에 버린다.
   *
   *  MutationObserver 의 콜백은 마이크로태스크로 **나중에** 불린다. 그래서 `applying`
   *  플래그만으로는 우리 변경을 걸러낼 수 없다 — 플래그가 이미 false 로 돌아간 뒤에
   *  우리 기록이 도착하기 때문이다. 그대로 두면 번역된 노드를 다시 번역 시도하고,
   *  같은 값을 다시 쓰는 것도 변경으로 기록되어 무한히 돈다. 실제로 그렇게 멈췄었다.
   *  큐를 비우고 나서 플래그를 내린다. */
  function release() {
    observer.takeRecords();
    applying = false;
  }

  function translateAll() {
    applying = true;
    try { walk(document.body); } finally { release(); }
  }

  function restoreAll() {
    applying = true;
    try {
      touchedText.forEach(function (node) {
        if (textOriginals.has(node)) node.nodeValue = textOriginals.get(node);
        textOriginals.delete(node);
      });
      touchedAttr.forEach(function (entry) {
        var store = attrOriginals.get(entry.element);
        if (store && Object.prototype.hasOwnProperty.call(store, entry.name)) {
          entry.element.setAttribute(entry.name, store[entry.name]);
          delete store[entry.name];
        }
      });
      touchedText = [];
      touchedAttr = [];
      restoreBlocks();
    } finally { release(); }
  }

  // app.js 가 화면을 다시 그릴 때마다 새 영어 노드가 들어온다. 그리는 쪽에 훅이
  // 없으므로 바깥에서 지켜본다. 우리가 만든 변화로 우리가 다시 불리지 않도록
  // `applying` 으로 끊는다.
  var observer = new MutationObserver(function (records) {
    if (applying || lang !== "ko") return;
    applying = true;
    try {
      records.forEach(function (record) {
        if (record.type === "characterData") { applyToTextNode(record.target); return; }
        if (record.type === "attributes") { applyToAttrs(record.target); return; }
        Array.prototype.forEach.call(record.addedNodes, walk);
      });
    } finally { release(); }
  });

  // ── 언어 전환 ───────────────────────────────────────────────────────────────
  function setLang(next, options) {
    options = options || {};
    var target = next === "ko" ? "ko" : "en";
    if (target === lang && !options.force) return;
    lang = target;

    // WCAG 2.2 SC 3.1.1. 한국어를 보여주면서 lang="en" 이면 스크린리더가 한국어를
    // 영어 발음으로 읽는다. 화면 언어와 이 속성은 항상 함께 움직인다.
    document.documentElement.setAttribute("lang", lang);

    if (lang === "ko") translateAll(); else restoreAll();

    // sessionStorage 를 쓴다(localStorage 아님). 탭을 닫으면 선택이 사라진다.
    //
    // 이 토글은 제품 소유자를 위한 임시 읽기 보조이고, 제출물의 정본은 영어다. localStorage
    // 였을 때는 한 번 켠 한국어가 새로고침과 재방문을 넘어 살아남았고, 그러면 데모 도중이나
    // 심사위원이 링크를 열었을 때 한국어 화면이 뜰 수 있다. 편의보다 그 사고를 막는 쪽이 크다.
    // 탭 안에서는 여전히 유지되므로 읽다가 새로고침해도 되돌아가지 않는다.
    try { window.sessionStorage.setItem("realdoor.lang", lang); } catch (e) { /* 사설 모드 등 */ }
    updateToggle();

    if (options.announce !== false) {
      // app.js 의 announce() 와 같은 라이브 리전이다. 그 함수는 클로저 안에 있어
      // 밖에서 부를 수 없으므로, 같은 노드에 같은 방식으로 쓴다.
      var live = document.getElementById("live-status");
      if (live) live.textContent = lang === "ko" ? "화면 언어를 한국어로 바꿨습니다." : "Page language switched to English.";
    }
  }

  function updateToggle() {
    var state = document.getElementById("lang-toggle-state");
    if (!state) return;
    // 토글의 보이는 라벨("한국어 / English")은 어느 언어에서도 읽히도록 고정이다.
    // 대신 현재 상태와 누르면 무슨 일이 생기는지를 숨은 텍스트로 알린다. 그 숨은
    // 텍스트는 지금 화면 언어로 쓰이고, lang 속성도 그에 맞춰 붙는다.
    if (lang === "ko") {
      state.setAttribute("lang", "ko");
      state.textContent = " — 현재 한국어, 누르면 영어로 바뀝니다";
    } else {
      state.setAttribute("lang", "en");
      state.textContent = " — currently English, activate for Korean";
    }
    var button = document.getElementById("lang-toggle");
    if (button) button.setAttribute("aria-pressed", lang === "ko" ? "true" : "false");
  }

  // ── 초기 언어 결정 ──────────────────────────────────────────────────────────
  // 기본값은 영어다. 저장된 값이 없으면 무조건 영어이고, 브라우저 언어는 보지 않는다.
  // 한국어는 명시적으로 켤 때만 켜진다: ?lang=ko 또는 지난번에 직접 켠 기록.
  function initialLang() {
    var query = null;
    try {
      query = new URLSearchParams(window.location.search).get("lang");
    } catch (e) { query = null; }
    if (query === "ko" || query === "en") return query;
    var stored = null;
    try { stored = window.sessionStorage.getItem("realdoor.lang"); } catch (e) { stored = null; }
    return stored === "ko" ? "ko" : "en";
  }

  function boot() {
    var toggle = document.getElementById("lang-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        setLang(lang === "ko" ? "en" : "ko");
      });
    }
    observer.observe(document.body, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATTRS
    });
    setLang(initialLang(), { force: true, announce: false });
  }

  // 이 스크립트는 app.js 보다 먼저 실행된다. app.js 가 그려 넣는 것은 위의
  // 옵저버가 잡고, 이미 HTML 에 있던 것은 boot() 의 첫 훑기가 잡는다.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.RealDoorI18n = { setLang: setLang, lang: function () { return lang; }, lookup: lookup };
})();
