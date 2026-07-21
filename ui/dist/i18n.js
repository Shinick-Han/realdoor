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
 * 준비 상태를 판정 어휘로 옮기지 않는다. READY_TO_REVIEW 는 "검토 준비됨"이지
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
    "Get your paperwork ready. A person decides the rest.": "서류를 준비하세요. 나머지는 사람이 결정합니다.",
    "This service reports document readiness only. It does not decide eligibility, and nothing on this screen means approved, denied, or ineligible. A qualified housing professional makes that determination.":
      "이 서비스는 서류의 준비 상태만 알려 드립니다. 자격은 판정하지 않습니다. 이 화면의 어떤 내용도 승인·거절·부적격을 뜻하지 않습니다. 그 판단은 공인 주택 전문가가 합니다.",
    "Household": "세대",
    "Data source: loading…": "데이터 출처: 불러오는 중…",
    "About this service": "이 서비스에 대하여",
    "How this works, and how we tested it": "어떻게 동작하는지, 그리고 어떻게 검증했는지",

    // ── index.html: 시작 화면 ───────────────────────────────────────────────
    "Get your housing documents ready for a person to review":
      "주택 서류를 사람이 검토할 수 있는 상태로 만드세요",
    "RealDoor reads the documents for one household, shows you where on the page every value came from, and tells you what is still missing or out of date. It does not decide whether anyone qualifies for anything — a housing professional does that.":
      "RealDoor 는 한 세대의 서류를 읽고, 각 값이 문서의 어느 위치에서 나왔는지 보여주고, 아직 없거나 기한이 지난 것이 무엇인지 알려 줍니다. 누구에게 자격이 있는지는 판정하지 않습니다 — 그것은 주택 전문가가 합니다.",
    "Before you start": "시작하기 전에",
    // ⚠ 이 문단의 영어는 업로드 기능이 들어오면서 바뀌었다. 예전 한국어는 "올릴 것도
    //   없고" 라고 말했는데, 이제 1단계에 올리기 패널이 있으므로 그 문장은 거짓이다.
    //   영어가 바뀌면 사전 키가 빗나가 저절로 영어로 남으므로 낡은 한국어가 화면에
    //   뜨지는 않았지만, 새 키로 옮겨 적으면서 "올릴 필요는 없다(없는 게 아니라)" 로
    //   뜻을 맞춘다.
    "This walkthrough takes about ten minutes. The documents for the household you choose above are already loaded, so you can go straight through it without uploading anything. Step 1 also lets you read a synthetic document of your own, held in memory for this session only. Nothing is sent anywhere. You can stop at any step and your work stays on this device.":
      "이 과정은 약 10분 걸립니다. 위에서 고른 세대의 서류는 이미 불러와 있어서, 아무것도 올리지 않고 그대로 끝까지 진행하실 수 있습니다. 1단계에서는 직접 만드신 합성 문서를 올려 읽어 볼 수도 있습니다. 그 문서는 이번 세션의 메모리에만 있습니다. 어디로도 전송되지 않습니다. 어느 단계에서든 멈출 수 있고 작업 내용은 이 기기에 남습니다.",
    "What happens, in order": "진행 순서",

    // ── index.html: 각 단계의 제목과 안내문 ─────────────────────────────────
    "Step 1 of 6": "6단계 중 1단계",
    "Step 2 of 6": "6단계 중 2단계",
    "Step 3 of 6": "6단계 중 3단계",
    "Step 4 of 6": "6단계 중 4단계",
    "Step 5 of 6": "6단계 중 5단계",
    "Step 6 of 6": "6단계 중 6단계",

    "Check the values we read from your documents": "서류에서 읽어낸 값을 확인하세요",
    "Each value below is shown together with the box on the page it was read from. Choose a field name to light up its box. Nothing here is inferred about the person.":
      "아래의 각 값은 그것을 읽어낸 문서상의 근거 위치와 함께 표시됩니다. 항목 이름을 고르면 그 위치가 켜집니다. 여기에서 사람에 대해 추측한 것은 하나도 없습니다.",

    "Correct a value we read wrong": "잘못 읽은 값을 바로잡으세요",

    // U10: 제품의 핵심 약속이 한국어 토글에서 영어로 남아 있었다. 우선순위대로 옮긴다 —
    // 머리말 선언문 먼저, 그다음 세입자용 약속 문장들. 인용문(규칙·출처 원문)과
    // 심사위원용 설계 근거(screen-how)는 그대로 영어로 둔다.
    "We get your file to the person who decides, complete the first time you hand it over. What we cannot tell you is the outcome — and no software can, because that decision needs checks that are not in these documents. Nothing on this screen means approved, denied, or ineligible; a qualified housing professional decides that.":
      "저희는 판단하는 사람에게 당신의 파일을, 처음 건네드릴 때 온전한 상태로 전달합니다. 저희가 말씀드릴 수 없는 것은 그 결과입니다 — 어떤 소프트웨어도 말할 수 없습니다. 그 판단에는 이 서류에 없는 확인들이 필요하기 때문입니다. 이 화면의 어떤 내용도 승인·거절·부적격을 뜻하지 않습니다. 그 판단은 공인 주택 전문가가 합니다.",
    "Anything we could not read, or could not be sure of, is listed here — on every screen, whichever step you are on.":
      "저희가 읽지 못했거나 확신하지 못한 것은 무엇이든 여기에 나열됩니다 — 어느 단계에 계시든 모든 화면에서요.",
    "RealDoor reads a document you give it and shows you where on the page every value came from. Each value is shown together with the box it was read from; choose a field name to light up its box. Nothing here is inferred about the person.":
      "RealDoor 는 당신이 준 문서를 읽고, 각 값이 문서의 어느 위치에서 나왔는지 보여 드립니다. 각 값은 그것을 읽어낸 상자와 함께 표시됩니다. 항목 이름을 고르면 그 상자가 켜집니다. 여기에서 사람에 대해 추측한 것은 없습니다.",
    "Choose a PDF and RealDoor reads it, then shows you every value it took out of it and the box on the page each one came from. It is read on its own: nothing else has to be open first, and reading it changes nothing anywhere else.":
      "PDF 를 고르시면 RealDoor 가 읽고, 거기서 뽑아낸 모든 값과 각 값이 나온 문서상의 상자를 보여 드립니다. 이 문서는 따로 읽힙니다: 먼저 열려 있어야 할 것이 없고, 읽어도 다른 어떤 것도 바뀌지 않습니다.",
    "Each row below shows what we read off this page. If a value is right, choose Confirm. If it is wrong, choose “This is wrong — fix it”: the row opens a box where you type what the page really says, or you point at the spot on the page and check our reading of it before you save. Confirming does not change the value or any number below it; it records that you read it.":
      "아래의 각 행에는 저희가 이 페이지에서 읽어낸 내용이 표시됩니다. 값이 맞으면 확인을 누르세요. 틀렸으면 “잘못 읽었어요 — 고치기”를 누르세요. 행에 입력칸이 열리고, 페이지가 실제로 말하는 값을 직접 입력하거나, 페이지 위의 그 자리를 가리켜 저희가 읽은 내용을 확인한 뒤 저장할 수 있습니다. 확인은 값이나 그 아래 어떤 숫자도 바꾸지 않습니다. 당신이 그것을 읽었다는 사실을 기록할 뿐입니다.",
    "If you would rather look around first, this copy carries six made-up household files. They belong to nobody. Everything the six steps do — the evidence boxes, the corrections, the checklist, the packet — works the same on them as on a document of your own.":
      "먼저 둘러보고 싶으시면, 이 사본에는 지어낸 세대 파일 여섯 개가 들어 있습니다. 누구의 것도 아닙니다. 여섯 단계가 하는 모든 것 — 근거 상자, 정정, 점검 목록, 서류 묶음 — 은 당신의 문서에서와 똑같이 그것들에서도 작동합니다.",
    "It also states how many values you checked and lists the actions taken in this session, with the rule versions that applied. That log holds no document contents and none of the values themselves.":
      "또한 당신이 확인한 값이 몇 개인지 밝히고, 이번 세션에서 이루어진 작업을 적용된 규칙 버전과 함께 나열합니다. 그 기록에는 문서 내용도, 값 자체도 담기지 않습니다.",
    "Nothing is waiting on you.": "당신을 기다리는 것은 없습니다.",

    // U12: 어디로도 라우팅되지 않은 질문 — 막다른 기권이 아니라 다음 걸음을 준다.
    "This isn't one this tool can answer — here is where to take it":
      "이건 이 도구가 답할 수 있는 질문이 아닙니다 — 어디로 가져가면 되는지 알려 드립니다",
    "This tool only answers questions about the housing-income rules: the frozen income limits, how income is added up over a year, and what a document needs. Yours is not one of those. That is fine to ask — it is just not something this tool can look up.":
      "이 도구는 주택 소득 규칙에 관한 질문만 답합니다: 동결된 소득 상한, 1년치 소득을 어떻게 합산하는지, 그리고 서류에 무엇이 필요한지입니다. 물으신 것은 그중 하나가 아닙니다. 물으셔도 괜찮습니다 — 다만 이 도구가 찾아볼 수 있는 것이 아닐 뿐입니다.",
    "Where a question like this belongs:": "이런 질문이 가야 할 곳:",
    "your property manager or a housing worker can answer it. This tool cannot.":
      "관리사무소나 주택 담당자가 답해 줄 수 있습니다. 이 도구는 답할 수 없습니다.",
    "What you can ask here:": "여기서 물어볼 수 있는 것:",
    "questions about the rules. Step 3 lists them — for example, what the frozen income limit is, how a year of income is added up, or what is still missing or out of date.":
      "규칙에 관한 질문입니다. 3단계에 목록이 있습니다 — 예를 들어, 동결된 소득 상한이 얼마인지, 1년치 소득을 어떻게 합산하는지, 또는 아직 없거나 기한이 지난 것이 무엇인지입니다.",

    // U9: 계산 패널이 무엇인지 한 줄로. 소득원이 하나뿐이면 두 패널이 같은 식을 보이므로.
    "This is your wage income on its own: one pay period, times the number of pay periods in a year.":
      "이것은 급여 소득만 따로 본 것입니다: 한 지급 주기를, 1년 안의 지급 횟수만큼 곱한 값입니다.",
    "This is your gig income on its own.": "이것은 긱(gig) 소득만 따로 본 것입니다.",
    "This is your whole yearly income: every income line above, added together. With one income source it matches that line; with more than one, it is their sum.":
      "이것은 한 해 전체 소득입니다: 위의 모든 소득 항목을 더한 값입니다. 소득원이 하나면 그 항목과 같고, 둘 이상이면 그것들의 합입니다.",

    // U4: 문서가 소프트웨어에 명령을 심으려 한 경우의 안내. 공격 문구는 신청자의 값이
    // 아니므로 값 표에서 빼고, 대신 여기서 "당신에 대한 것이 아니라 문서에 대한 사실"이라고
    // 설명한다. 원문(격리된 텍스트)은 기술 세부정보에 그대로 남는다.
    "Something in this document tried to give the software an instruction":
      "이 문서 안의 무언가가 소프트웨어에 명령을 주려 했습니다",
    "We filed it as text and never ran it. It changed none of your values and none of the figures on this file. There is nothing for you to do about it, and it is not held against you — it is a fact about the document, not about you.":
      "저희는 그것을 글자로만 보관하고 실행하지 않았습니다. 당신의 어떤 값도, 이 파일의 어떤 수치도 바꾸지 않았습니다. 당신이 하실 일은 없고, 불리하게 작용하지도 않습니다 — 이것은 당신이 아니라 문서에 대한 사실입니다.",
    "Captured as quarantined data under rule CH-SAFETY-001, which is cited on this report because of it. The text is stored and carried into the packet so a reviewer can see it; it never reaches the calculation.":
      "규칙 CH-SAFETY-001 에 따라 격리된 데이터로 포착했으며, 그 때문에 이 리포트에 해당 규칙이 인용됩니다. 이 글자는 검토자가 볼 수 있도록 보관되어 패킷에 실리지만, 계산에는 결코 도달하지 않습니다.",

    "Ask what a housing rule says": "주택 규칙이 뭐라고 하는지 물어보세요",
    "Every answer carries its rule id, the authority behind it, the date it took effect, and where in the source it is written.":
      "모든 답변에는 규칙 id, 그 근거가 되는 기관, 시행일, 그리고 원문의 어디에 적혀 있는지가 함께 붙습니다.",

    "See how your yearly income figure was worked out": "연 소득 금액이 어떻게 산출되었는지 보세요",
    "Inputs, formula, result, threshold, comparison, effective date. A comparison is not a determination.":
      "입력값, 계산식, 결과, 기준액, 비교, 시행일. 비교는 판정이 아닙니다.",

    "See what is missing or out of date": "무엇이 없거나 기한이 지났는지 보세요",
    "What is present, what is missing, what has expired, and what could not be dated — with the one thing you can do about each.":
      "무엇이 있고, 무엇이 없고, 무엇의 기한이 지났고, 무엇의 날짜를 알 수 없었는지 — 각각에 대해 할 수 있는 한 가지와 함께.",

    "Check what we found, then take your packet": "찾아낸 내용을 확인하고, 신청 서류 묶음을 받으세요",
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
    // ⚠ 예전 한국어는 "업로드가 아니라 미리 불러와 있으며" 였다. 업로드 패널이
    //   생기면서 이제 **둘 다**이므로 그 문장은 거짓이다. 영어의 "Either way" 가
    //   하는 일(두 경로 모두 근거 위치를 단다)을 한국어에서도 그대로 남긴다.
    "— walkthrough step 1. The household's documents are pre-loaded, and the panel at the top of that step reads a synthetic document you upload yourself. Either way every value carries the box on the page it came from. An uploaded document is read on its own and is not added to the household, because working out whose document it is and what it replaces would mean guessing.":
      "— 진행 과정 1단계. 세대의 서류는 미리 불러와 있고, 그 단계 맨 위의 패널에서는 직접 올리신 합성 문서를 읽습니다. 어느 쪽이든 모든 값은 그것이 나온 문서상의 근거 위치를 달고 있습니다. 올리신 문서는 그 문서 하나만 놓고 읽으며 세대에 합치지 않습니다. 누구의 문서인지, 무엇을 대신하는지를 따지려면 짐작해야 하기 때문입니다.",
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
    "Our measured results, including the parts we did not run. Published as measured, whether or not they flatter us.":
      "우리가 측정한 결과입니다. 실행하지 않은 항목까지 포함합니다. 우리에게 유리하든 아니든, 측정된 그대로 공개합니다.",

    // ── index.html: 사이드 레일과 푸터 ──────────────────────────────────────
    "What this system is unsure about": "이 시스템이 확신하지 못하는 것",
    "Always visible, never folded away. A system that knows something and does not say it is the failure this product exists to prevent.":
      "항상 보이고, 접어 숨기지 않습니다. 알면서 말하지 않는 시스템 — 그것이 이 제품이 막으려고 존재하는 실패입니다.",
    "About this build": "이 빌드에 대하여",

    // ── app.js: 진행 과정 목록의 설명문 ─────────────────────────────────────
    "See each value we read and the exact box on the page it came from.":
      "읽어낸 각 값과, 그 값이 나온 문서상의 정확한 근거 위치를 봅니다.",
    "Change anything we got wrong, and see whether it changed the numbers.":
      "우리가 틀린 것을 바꾸고, 그것이 숫자를 바꿨는지 봅니다.",
    "Get an answer with the rule id, the authority, and the date it took effect.":
      "규칙 id, 근거 기관, 시행일이 함께 붙은 답변을 받습니다.",
    "Inputs, formula, result and the threshold it is compared against.":
      "입력값, 계산식, 결과, 그리고 비교 대상이 되는 기준액.",
    "The full checklist, and the one thing you can do about each open item.":
      "전체 점검 목록과, 남은 항목마다 할 수 있는 한 가지.",
    "Review everything in one place, change what is wrong, then download it.":
      "모든 것을 한자리에서 검토하고, 틀린 것을 고친 뒤 내려받습니다.",

    // ── app.js: 단계 표시기의 짧은 이름 ─────────────────────────────────────
    "Your documents": "내 서류",
    "Corrections": "정정",
    "Rules": "규칙",
    "The calculation": "계산",
    "Missing or expired": "없음 또는 기한 지남",
    "Your packet": "내 신청 서류 묶음",
    "Progress": "진행 상황",
    "— completed": "— 완료됨",
    "— current step": "— 현재 단계",
    "— not completed": "— 아직 안 됨",

    // ── app.js: 이동 버튼 ───────────────────────────────────────────────────
    "Start step 1": "1단계 시작",
    "Go back to where you were": "보던 곳으로 돌아가기",
    "Return to what we found": "찾아낸 내용으로 돌아가기",
    "Back to the start": "처음으로",

    // ── app.js: 준비 상태 ────────────────────────────────────────────────
    // 판정 어휘 금지의 핵심 지점. "적격/부적격"이 아니라 "검토 준비"와 "남은 항목"이다.
    "Ready for a person to review": "사람이 검토할 준비가 되었습니다",
    "Every required document is present, current under the frozen 60-day convention, internally consistent, and traceable to a box on the page. This is not approval, and it is not an eligibility outcome.":
      "필요한 서류가 모두 있고, 이 프로젝트가 따르는 60일 기준으로 유효하며, 서로 모순이 없고, 문서상의 근거 위치까지 추적됩니다. 이것은 승인이 아니며, 자격에 대한 결론도 아닙니다.",
    "Not ready yet — items still open": "아직 준비되지 않았습니다 — 남은 항목이 있습니다",
    "Something is missing, out of date, undatable, or inconsistent. This is not a refusal and it is not an eligibility outcome; it is a list of what to fix.":
      "무언가가 없거나, 기한이 지났거나, 날짜를 알 수 없거나, 서로 맞지 않습니다. 이것은 거절이 아니며 자격에 대한 결론도 아닙니다. 고쳐야 할 것들의 목록입니다.",

    // ── app.js: 비교 문장 ("비교는 판정이 아니다") ──────────────────────────
    "The annualized amount is at or below the frozen 60% threshold for this household size.":
      "연환산 금액이 이 세대원 수에 대한 동결된 60% 기준액 이하입니다.",
    "The annualized amount is above the frozen 60% threshold for this household size.":
      "연환산 금액이 이 세대원 수에 대한 동결된 60% 기준액을 넘습니다.",
    "No frozen threshold applies to this figure, so no comparison is made.":
      "이 금액에 적용되는 동결된 기준액이 없어서 비교하지 않습니다.",
    "A comparison is not a determination.": "비교는 판정이 아닙니다.",
    "This line says how one number sits against a frozen table. It does not say what happens next; a qualified housing professional decides that.":
      "이 줄은 숫자 하나가 동결된 표에 대해 어디에 놓이는지를 말할 뿐입니다. 그다음에 무슨 일이 일어나는지는 말하지 않습니다. 그것은 공인 주택 전문가가 정합니다.",

    // ── app.js: 항목 상태와 근거 종류 ───────────────────────────────────────
    "Present": "있음",
    "Missing": "없음",
    "Expired": "기한 지남",
    "Undatable": "날짜를 알 수 없음",
    "Unreadable": "읽지 못함",
    "Read from the document": "문서에서 읽음",
    "Confirmed by the renter": "세입자가 확인함",
    "Corrected by the renter": "세입자가 정정함",
    "High": "높음",
    "Low": "낮음",
    "Abstained — a person must supply this": "말하지 않았습니다 — 사람이 입력해야 합니다",
    "Not read — a person must supply this": "읽지 못함 — 사람이 입력해야 합니다",

    // ── app.js: 기대 필드의 부재(문서 관점 안내 + 부재 확인) ─────────────────
    // 준비도 관행은 빠진 필수 증거를 NEEDS_REVIEW 로 보낸다. 이 문장들은 기계의 자백
    // ("no label ... was found") 대신 문서 관점으로 말한다. 판정 어휘 금지 규율 그대로:
    // "없다"는 서류에 대한 사실이지 사람에 대한 판정이 아니다.
    "This document does not show this": "이 문서에는 이 값이 없습니다",
    "Checked by you": "직접 확인함",
    "Not read — type what this should say, then choose Confirm.":
      "읽지 못함 — 들어가야 할 값을 입력하고 확인을 누르세요.",
    "the reader recorded no note": "판독기가 남긴 기록이 없습니다",
    // 발급처 표현 (absenceNotice 의 issuerWords)
    "your employer": "고용주",
    "the benefits office": "급여를 지급한 기관",
    "the app you work for": "일하시는 앱 회사",
    "whoever gave you the form": "이 양식을 주신 곳",
    "whoever issued this document": "이 문서를 발행한 곳",
    "your bank or the app you work for": "거래 은행이나 일하시는 앱 회사",
    // 부재 안내가 이름을 부르는 항목들 (fieldWords: 밑줄을 공백으로). 이미 위쪽 사전에
    // 있는 "gross pay"·"pay frequency" 는 여기 다시 적지 않는다 — 중복 키는 조용히
    // 덮어쓰므로, 한 사전에 한 번만 있어야 한다.
    "person name": "이름",
    "pay date": "지급일",
    "pay period start": "급여 기간 시작일",
    "pay period end": "급여 기간 종료일",
    "regular hours": "정규 근무시간",
    "hourly rate": "시급",
    "net pay": "실수령액",
    "household size": "세대원 수",
    "application date": "신청일",
    "address": "주소",
    "document date": "문서 날짜",
    "weekly hours": "주당 근무시간",
    "monthly benefit": "월 수급액",
    "benefit frequency": "수급 주기",
    "statement month": "명세 대상 월",
    "gross receipts": "총 수입",
    "platform fees": "플랫폼 수수료",
    "benefit letter": "수급 결정 통지서",

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
    "Still current?": "아직 유효한가요?",
    "No day in the date": "날짜에 일(日)이 없음",
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
    "Box (pt)": "근거 위치 (pt)",
    "no box": "근거 위치 없음",
    "Boxes are in PDF points, bottom-left origin, as [x0, y0, x1, y1].":
      "근거 위치는 PDF 포인트 단위이며, 좌하단이 원점인 [x0, y0, x1, y1] 형식입니다.",
    "Page 1 as rendered by the server. Each rectangle is the box the value was read from; the same coordinates are listed as text in the table below.":
      "서버가 그린 1페이지입니다. 각 사각형은 값을 읽어낸 근거 위치이고, 같은 좌표가 아래 표에 글자로 적혀 있습니다.",
    "Loading the page image…": "페이지 이미지를 불러오는 중…",
    "No server is running, so the scanned page cannot be rasterised.":
      "서버가 떠 있지 않아 스캔한 페이지를 이미지로 만들 수 없습니다.",
    "This is a schematic, not the document:": "이것은 문서가 아니라 개략도입니다:",
    "each rectangle is at the real extracted coordinates and holds the real source text, drawn with the same bottom-left-origin conversion the server uses. Exact coordinates are in the table below.":
      "각 사각형은 실제로 추출된 좌표에 놓여 있고 실제 원문 글자를 담고 있으며, 서버가 쓰는 것과 같은 좌하단 원점 변환으로 그려졌습니다. 정확한 좌표는 아래 표에 있습니다.",

    // ── app.js: 정정 화면 ───────────────────────────────────────────────────
    "Your correction is recorded, and it may still not be used": "정정은 기록되지만, 그래도 쓰이지 않을 수 있습니다",
    "A correction changes what the file says. It does not always change your yearly income figure. Here is why: if your new figure no longer matches the hours and pay rate printed on the same document, that document can no longer show what your regular pay is. When that happens the system tells you, instead of quietly using the new number.":
      "정정은 파일에 적힌 내용을 바꿉니다. 그렇다고 연 소득 금액이 늘 바뀌는 것은 아닙니다. 이유는 이렇습니다: 정정한 숫자가 같은 문서에 인쇄된 근무시간·시급과 더 이상 맞지 않으면, 그 문서는 정기 급여가 얼마인지를 더는 보여줄 수 없습니다. 그럴 때 시스템은 새 숫자를 조용히 쓰지 않고 그 사실을 알려 드립니다.",
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
    "Readiness": "준비 상태",
    "Open questions": "남은 물음",
    "(changed)": "(바뀜)",
    "(unchanged)": "(그대로)",
    "below or equal": "이하",
    "above": "초과",
    "no frozen threshold": "동결된 기준액 없음",
    "The threshold moves when household size changes because the frozen HUD table is indexed by household size (rule HUD-MTSP-002). The amount moves only when the recurring base changes.":
      "동결된 HUD 표가 세대원 수로 색인되어 있기 때문에(규칙 HUD-MTSP-002), 세대원 수가 바뀌면 기준액이 움직입니다. 금액은 정기 급여의 기준이 바뀔 때만 움직입니다.",

    /* ── 랜딩 화면 제거에 따라 새로 생긴 문장들 ────────────────────────────────
     *
     * 기존 항목은 하나도 지우지 않았다. 랜딩 화면의 제목·첫 단락 키(위쪽)는 이제 화면에
     * 나타나지 않지만 사전에 그대로 남겨 둔다 — 사전 키가 안 맞으면 저절로 영어로 남는
     * 구조이므로 쓰이지 않는 키는 해를 끼치지 않고, 지우면 되돌리기가 어려워진다.
     *
     * "Before you start" 와 "What happens, in order" 의 한국어는 위에 이미 있고, 그 두
     * 덩어리가 판정 화면(screen-how)으로 옮겨졌을 뿐이라 키가 그대로 맞는다. */

    // 1단계 도입문. 헤더의 상시 고지가 이미 말하는 내용을 반복하지 않는다.
    "RealDoor reads the documents for one household and shows you where on the page every value came from. On this step, each value is shown together with the box it was read from. Choose a field name to light up its box. Nothing here is inferred about the person.":
      "RealDoor 는 한 세대의 서류를 읽고, 각 값이 문서의 어느 위치에서 나왔는지 보여 줍니다. 이 단계에서는 각 값이 그것을 읽어낸 근거 위치와 함께 표시됩니다. 항목 이름을 고르면 그 위치가 켜집니다. 여기에서 사람에 대해 추측한 것은 하나도 없습니다.",

    // 판정 화면으로 옮겨 간 목차에 붙는 안내문.
    "The six steps of the walkthrough, in the order they are presented. The walkthrough starts on step 1, so this list is a description of it rather than a gate in front of it.":
      "진행 과정 여섯 단계를, 제시되는 순서대로 적은 것입니다. 진행은 1단계에서 바로 시작하므로, 이 목록은 앞을 막는 관문이 아니라 설명입니다.",

    // ── 모든 화면에 붙는 질문 상자 ─────────────────────────────────────────
    "Ask about a housing rule": "주택 규칙에 대해 물어보기",
    "You can ask from any step, in your own words. The answer opens below this box, with the rule id, the authority behind it and the date it took effect. Step 3 holds the recorded questions and explains what a citation carries.":
      "어느 단계에서든 자기 말로 물어보실 수 있습니다. 답변은 이 상자 바로 아래에 열리며, 규칙 id, 그 근거가 되는 기관, 시행일이 함께 붙습니다. 기록된 질문과 인용이 무엇을 담는지에 대한 설명은 3단계에 있습니다.",
    "No question has been asked yet. The answer to one appears here, in this same place on every screen, and the page moves you to it when it arrives.":
      "아직 아무 질문도 하지 않으셨습니다. 질문에 대한 답변은 여기, 모든 화면에서 같은 자리에 나타나고, 답변이 오면 화면이 그리로 옮겨 드립니다.",
    "You deleted this session, so there is nothing left to answer a question with. Starting again loads the household from the pack as a new session.":
      "이 세션을 지우셨기 때문에, 질문에 답할 것이 남아 있지 않습니다. 다시 시작하면 세대 자료를 팩에서 새 세션으로 불러옵니다.",
    "To ask in your own words, use the box at the foot of this page. It is on every screen, and its answers open in the same place these ones do.":
      "자기 말로 물어보시려면 이 페이지 맨 아래의 입력 상자를 쓰세요. 그 상자는 모든 화면에 있고, 그 답변도 여기 답변과 같은 자리에 열립니다.",

    // ── 화면 아래에 고정된 질문 상자(dock) ─────────────────────────────────
    // 위 두 문장은 상자가 "페이지 맨 아래"에 있던 시절의 것이다. 영어가 바뀌면 사전
    // 키가 빗나가 저절로 영어로 남으므로 낡은 한국어가 화면에 뜨지는 않지만, 새 키로
    // 옮겨 적는다. 옛 키는 지우지 않는다 — 지우는 것은 "추가만" 이 아니다.
    "To ask in your own words, use the box pinned at the bottom of the screen. It is there on every step, and its answers open in the same place these ones do.":
      "자기 말로 물어보시려면 화면 아래에 고정된 입력 상자를 쓰세요. 모든 단계에 있고, 그 답변도 여기 답변과 같은 자리에 열립니다.",
    "No question has been asked yet. The box to ask one is pinned at the bottom of the screen; the answer appears here, in this same place on every screen, and the page moves you to it when it arrives.":
      "아직 아무 질문도 하지 않으셨습니다. 물어보는 상자는 화면 아래에 고정되어 있고, 답변은 여기, 모든 화면에서 같은 자리에 나타나며, 답변이 오면 화면이 그리로 옮겨 드립니다.",
    "Build details": "빌드 정보",
    "Then open http://127.0.0.1:8077 and ask from any screen.":
      "그런 다음 http://127.0.0.1:8077 을 열면 어느 화면에서든 물어보실 수 있습니다.",
    "Without a server, the questions this build did record can still be asked from step 3, and their answers open here.":
      "서버가 없어도, 이 빌드가 기록해 둔 질문들은 3단계에서 그대로 물어볼 수 있고, 그 답변은 여기에 열립니다.",

    // ── app.js: 규칙 질문 화면 ─────────────────────────────────────────────
    "Ask about a rule": "규칙에 대해 물어보기",
    "Routed to deterministic rule handlers. No document text reaches the calculation.":
      "결정론적 규칙 처리기로 넘어갑니다. 문서의 글자는 계산에 도달하지 않습니다.",
    "Ask": "묻기",
    "Recorded questions": "기록된 질문",
    "No recorded answer for that wording": "그 표현으로 기록된 답변이 없습니다",
    "Offline, this app can only replay questions the pipeline actually answered. It will not improvise an answer about a housing rule. Choose one of the recorded questions, or start the API for free-form questions.":
      "오프라인에서는 파이프라인이 실제로 답한 질문만 재생할 수 있습니다. 주택 규칙에 대한 답을 지어내지 않습니다. 기록된 질문 중 하나를 고르거나, 자유롭게 묻고 싶으면 API 를 실행하세요.",
    // U3: "거부"는 신청자에게 문이 닫히는 말로 읽힌다. 실제로 일어난 일은 더 좁다 —
    // 판단을 그 일을 하는 사람에게 넘긴 것이다. 거부 자체는 그대로다.
    "Only a person can decide that — here is what we can tell you":
      "그 판단은 사람만 할 수 있습니다 — 저희가 알려 드릴 수 있는 것은 이렇습니다",
    "We cannot tell you whether you will get this home, and we will not guess. A housing worker decides that. It takes checks this service does not hold: proof of who lives with you, your income confirmed by an outside source, and status checks that are not in your file.":
      "이 집을 얻으시게 될지는 저희가 말씀드릴 수 없고, 짐작하지도 않습니다. 그 판단은 주택 담당자가 합니다. 그러려면 이 서비스가 갖고 있지 않은 확인이 필요합니다 — 누가 함께 사는지에 대한 증빙, 외부 기관이 확인한 소득, 그리고 파일에 없는 신분 확인입니다.",
    "Here is what we can tell you from your documents:": "서류에서 저희가 알려 드릴 수 있는 것은 이렇습니다:",
    "What your income adds up to over a year.": "소득이 1년 동안 얼마로 합산되는지.",
    "The income limit for a household your size.": "세대 인원수에 해당하는 소득 상한.",
    "How those two numbers compare.": "그 두 수치가 서로 어떻게 견주어지는지.",
    "What is still missing or out of date.": "아직 없거나 기한이 지난 것이 무엇인지.",
    "Those are facts about paperwork and arithmetic, not about you. Our job is to hand the person who decides a complete file, so they can decide the first time they read it.":
      "이것들은 서류와 계산에 대한 사실이지, 당신에 대한 사실이 아닙니다. 저희가 할 일은 판단하는 사람에게 온전한 파일을 건네어, 그가 처음 읽을 때 판단할 수 있게 하는 것입니다.",
    "The precise wording this service sends: ": "이 서비스가 보내는 정확한 문구: ",
    "Abstained — no answer given": "답하지 않았습니다 — 답을 내지 않았습니다",
    "Answer": "답변",
    "No answer is given for this question.": "이 질문에는 답을 내지 않습니다.",
    "What would resolve it:": "무엇이 있으면 풀리는지:",
    "Response kind:": "응답 종류:",

    // ── 중간 계층: 시스템이 질문을 **해석해서** 고른 답 ─────────────────────
    // 확신 어휘를 쓰지 않는다. "정확히 맞췄다"도 "틀렸다"도 아니고 "이렇게 읽었다"다.
    // gloss 는 API 가 보내는 영어 조각이라 아래 따로 옮긴다 — 옮기지 못한 것은
    // 영어로 남고, 그게 지어내는 것보다 낫다.
    "Answer, from how we read your question": "답변 — 질문을 이렇게 읽고 드린 답입니다",
    // U2: 해석 안내는 이제 답 아래 한 줄이다. 답이 먼저, 우리의 라우팅 이야기는 나중.
    "We read your question as one about": "질문을 다음에 대한 것으로 읽었습니다:",
    "We answered our best reading of your wording, not an exact match.":
      "표현이 정확히 일치하지 않아, 헤아린 최선의 읽기에 답했습니다.",
    "Your wording also sat close to several other questions this service answers, and it could not tell them apart. Take this as our best attempt at your question rather than a settled answer to it.":
      "게다가 이 표현은 이 서비스가 답하는 다른 몇 가지 질문과도 가까워서, 그것들과 구분하지 못했습니다. 확정된 답이 아니라 질문에 대한 최선의 시도로 읽어 주세요.",
    "If that is not what you meant, ask again in different words, or use a recorded question on step 3.":
      "뜻하신 바가 아니라면 다른 표현으로 다시 물어보시거나, 3단계의 기록된 질문을 쓰세요.",
    "Ask again in different words": "다른 표현으로 다시 묻기",
    // Technical details 안. 값(경로 이름·의도 이름)은 .mono 라서 번역되지 않는다.
    "Routed by:": "어느 층이 잡았는지:",
    "· intent:": "· 의도:",
    "Shape gate separated this intent:": "형태 게이트가 이 의도를 구분했는지:",
    ". Shares an answer profile with:": ". 같은 답 프로파일을 공유하는 것:",

    // gloss — api/route_llm.py 의 의도 표에서 오는 사람 말 조각.
    "the income limit figure for a household size": "세대 인원수에 해당하는 소득 상한 금액",
    "how a household's income adds up over a year": "한 세대의 소득이 1년 동안 어떻게 합산되는지",
    "how an income sits next to the limit figure": "소득이 상한 금액과 견주어 어디쯤인지",
    "which documents are present, missing or expired": "어떤 서류가 있고, 없고, 기한이 지났는지",
    "what this service is and is not allowed to state": "이 서비스가 말할 수 있는 것과 없는 것",
    "the date the limit figures took effect": "상한 금액이 시행된 날짜",
    "whether a unit is open, vacant or on a waitlist": "세대가 비어 있는지, 대기자 명단인지",
    "address geocoding precision codes": "주소 좌표 변환의 정밀도 코드",
    "text inside an uploaded document that reads as a command": "올린 문서 안에 명령처럼 적힌 문구",
    "the status of the 60-day document freshness convention": "60일 최신성 관행의 지위",
    "the federal statute the program rests on": "이 제도가 근거하는 연방 법률",
    "asking this service for a program determination": "이 서비스에 제도상의 판정을 요구하는 것",
    "asking to infer a protected characteristic": "보호받는 특성을 추론해 달라는 요구",
    "a document that is out of date": "기한이 지난 서류",
    "two figures that do not reconcile": "서로 맞지 않는 두 수치",
    "a malformed bounding box or schema error": "잘못된 좌표 상자나 스키마 오류",
    "a household size outside the supplied table": "제공된 표에 없는 세대 인원수",
    "a self-declared or unsigned figure": "본인이 적었거나 서명이 없는 수치",
    "a statement offered without a source or page": "출처나 쪽 표시 없이 나온 진술",
    "using figures from a different year": "다른 연도의 수치를 쓰는 것",
    "what the dataset does and does not contain": "이 데이터셋에 무엇이 들어 있고 없는지",
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
      "이 서비스는 준비 상태만 알려 드립니다. 자격 판정은 공인 주택 전문가가 합니다.",
    "This is not an eligibility determination. A qualified housing professional must decide.":
      "이것은 자격 판정이 아닙니다. 공인 주택 전문가가 판단해야 합니다.",
    "That text was treated as document content, not as an instruction. It did not change anything: the readiness calculations are deterministic code and no text from a document or question reaches them.":
      "그 문장은 지시가 아니라 문서의 내용으로 취급했습니다. 그래서 아무것도 바뀌지 않았습니다. 준비 상태 계산은 결정론적 코드이고, 문서나 질문에 적힌 어떤 글자도 그 계산에 닿지 않습니다.",
    "This session can only answer about its own household. Information about another applicant is never disclosed.":
      "이 세션은 자기 세대에 대해서만 답할 수 있습니다. 다른 신청자의 정보는 어떤 경우에도 공개하지 않습니다.",
    "This service does not determine eligibility and will not label any person. What it reports instead is a readiness status — READY_TO_REVIEW or NEEDS_REVIEW — with the reasons behind it, the annualized amount computed from the documents, the frozen threshold for the household size, and the comparison between those two numbers. Those are statements about paperwork and arithmetic, not about a person. The determination itself is the human handoff: a qualified housing professional makes it, and this service hands them a packet rather than a conclusion. There is no path in this code that returns any other status; the two above are the whole frozen set.":
      "이 서비스는 자격을 판정하지 않으며, 어떤 사람에게도 딱지를 붙이지 않습니다. 대신 알려 드리는 것은 준비 상태 — READY_TO_REVIEW 또는 NEEDS_REVIEW — 와 그렇게 본 이유들, 서류에서 계산한 연환산 금액, 그 세대원 수에 대한 동결된 기준액, 그리고 그 두 숫자의 비교입니다. 이것들은 서류와 산술에 대한 진술이지 사람에 대한 진술이 아닙니다. 판정 자체는 사람에게 넘기는 일입니다. 공인 주택 전문가가 판정하고, 이 서비스는 결론이 아니라 서류 묶음을 건넵니다. 이 코드에는 다른 상태를 돌려주는 경로가 없습니다. 위의 둘이 동결된 전부입니다.",
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

    /* ── R26 감사: 기권 응답의 "무엇이 있으면 풀리는지" 문장들 ─────────────────
     * 기권은 재안내이지 판정이 아니다. 그런데 기권 다음 걸음을 말하는 resolve 문장이
     * 한국어 토글에서 영어로 남아 있었다 — 토글이 섬기는 바로 그 사람에게 다음 걸음이
     * 사라지는 셈이다. 아래는 situations.py / answer_rules.py / abstain.py 의 resolve
     * 문장 전부다. 숫자·날짜가 박힌 것은 아래 RULES 에서 정규식으로 잡는다. */
    "supply the source document for any other figure so it can be cited or refused":
      "다른 수치가 적힌 원본 서류를 내 주세요. 그러면 그 서류를 인용하거나, 쓸 수 없는 이유를 말씀드립니다",
    "contact the property's management office or the local housing agency for current availability":
      "지금 비어 있는 집은 그 건물의 관리사무소나 지역 주택 기관에 문의해 주세요",
    "point the value at the page and box it came from, or withdraw it and re-extract":
      "그 값이 나온 페이지와 위치를 짚어 주거나, 값을 거두고 다시 읽으면 됩니다",
    "a human confirms which figure is the recurring one, or the employer reissues a stub whose components add up to its stated total":
      "어느 금액이 정기 급여인지 사람이 확인해 주거나, 항목 합계가 총액과 맞는 명세서를 고용주가 다시 발급하면 됩니다",
    "ask about a documented income amount, a required document, or a frozen threshold instead":
      "대신 서류에 적힌 소득 금액, 필요한 서류, 또는 동결된 기준액에 대해 물어보세요",
    "re-extract the field so its box lies inside the declared page, or drop the value and mark it for human entry":
      "근거 상자가 선언된 페이지 안에 들어오도록 값을 다시 읽거나, 값을 버리고 사람이 입력하도록 표시하면 됩니다",
    "upload an employer-issued letter, or bank deposits, platform records or a 1099 covering the same period":
      "고용주가 발급한 증명서를 올리거나, 같은 기간의 은행 입금 내역·플랫폼 기록·1099 를 올리면 됩니다",
    "re-run the request, or ask a housing professional":
      "요청을 다시 실행하시거나, 주택 전문가에게 물어보세요",
    "a housing professional answers this": "주택 전문가가 답해 줍니다",
    "the renter confirms the pay frequency, or uploads a stub that states it":
      "세입자가 급여 주기를 확인해 주거나, 급여 주기가 적힌 명세서를 올리면 됩니다",
    "a housing professional maps this frequency to an annual multiplier":
      "주택 전문가가 이 급여 주기를 연간 배수로 바꿔 주면 됩니다",
    "the renter confirms the amount, or re-uploads a legible document":
      "세입자가 금액을 확인해 주거나, 읽을 수 있는 서류를 다시 올리면 됩니다",
    "the renter confirms the value against the page":
      "세입자가 그 값을 문서와 대조해 확인해 주면 됩니다",
    "the renter confirms the value against the page image":
      "세입자가 그 값을 문서 이미지와 대조해 확인해 주면 됩니다",
    "a reviewer confirms the corrected amount against the page image before relying on it":
      "검토자가 정정된 금액을 문서 이미지와 대조해 확인한 뒤에 쓰면 됩니다",
    "the renter or employer confirms which stub reflects recurring pay":
      "어느 명세서가 정기 급여를 나타내는지 세입자 또는 고용주가 확인해 주면 됩니다",
    "a housing professional supplies the limit for this household size from the current HUD MTSP tables":
      "주택 전문가가 현행 HUD MTSP 표에서 이 세대원 수의 상한을 제공해 주면 됩니다",
    "the renter confirms the household size": "세대원 수를 확인해 주시면 됩니다",
    "resolve the income abstentions listed above": "위에 나열된 소득 관련 미확정 항목이 풀리면 됩니다",
    "the renter re-uploads a text-layer copy, or OCR is applied":
      "글자가 살아 있는 사본을 다시 올리시거나, OCR 로 읽으면 됩니다",
    "the renter confirms the income inputs": "세입자가 소득 입력값을 확인해 주면 됩니다",
    "supply the missing input": "빠진 입력값을 채워 주시면 됩니다",

    // R26: 기권 제목. 예전 제목("no answer given")의 사전 키만 있어서 새 제목이 영어로 남았다.
    "Abstained — no value given": "말하지 않았습니다 — 값을 내지 않았습니다",

    // R26: 질문 화면이 비교 enum 토큰 하나만 받았을 때 쓰는 평문 세 문장 (COMPARISON_PLAIN).
    "Your yearly income figure is at or below the income limit for your household size. That is a comparison of two numbers — it is not a decision about you.":
      "당신의 연 소득 금액이 세대원 수 기준 소득 상한 이하입니다. 이것은 두 숫자를 견준 것일 뿐, 당신에 대한 판단이 아닙니다.",
    "Your yearly income figure is above the income limit for your household size. That is a comparison of two numbers — it is not a decision about you, and it is not a refusal. A qualified housing worker decides, using checks this service does not hold.":
      "당신의 연 소득 금액이 세대원 수 기준 소득 상한을 넘습니다. 이것은 두 숫자를 견준 것일 뿐, 당신에 대한 판단도 거절도 아닙니다. 이 서비스가 갖고 있지 않은 확인을 거쳐, 공인 주택 담당자가 판단합니다.",
    "This service holds no published limit for a household of that size, so it makes no comparison. A housing worker can tell you which limit applies.":
      "이 서비스에는 그 세대원 수에 대한 공표된 상한이 없어서 비교하지 않습니다. 어떤 상한이 적용되는지는 주택 담당자가 알려 줄 수 있습니다.",

    // R26: 파일이 안 열린 채 물은 질문의 기권 — 다음 걸음(1단계)을 함께 준다.
    "no file is open, so there was nothing to answer from. Step 1 reads a document you upload, or opens a prepared example file. Then ask again.":
      "열려 있는 파일이 없어서, 답할 근거가 없었습니다. 1단계에서 직접 올린 문서를 읽거나 준비된 예시 파일을 열 수 있습니다. 그런 다음 다시 물어보세요.",

    // R26: 1단계 문서 요약의 날짜 기권 — 확인에서 멈추지 않고 다음 걸음을 준다.
    "If you know the exact date, enter it on step 2. Or ask for a copy that shows the full date. Step 5 lists this as an open item.":
      "정확한 날짜를 아시면 2단계에서 입력해 주세요. 아니면 날짜가 다 적힌 사본을 요청하세요. 5단계에 남은 항목으로 올라 있습니다.",

    // R26: 업로드 패널의 날짜 기권.
    "The date shows a month but no day, so we cannot count the 60-day window from it.":
      "날짜에 월까지만 있고 일(日)이 없어서, 거기서부터 60일 기간을 셀 수 없습니다.",
    "no date we could read on this document.": "이 문서에서 읽어낼 수 있는 날짜가 없습니다.",

    // R26: 4단계 계산 기권 — 수치가 나오지 않았거나 비교가 이루어지지 않았을 때.
    "We could not work out this figure, so no amount is shown.":
      "이 수치를 계산해 내지 못해서, 금액이 표시되지 않습니다.",
    "We could not work out this figure, so no amount is shown. The income limit itself is on file — what is missing is a yearly figure to set against it.":
      "이 수치를 계산해 내지 못해서, 금액이 표시되지 않습니다. 소득 상한 자체는 파일에 있습니다 — 빠진 것은 그 옆에 놓을 연 소득 금액입니다.",
    "We could not compare this figure with a limit. We do not hold a limit for a household of this size.":
      "이 수치를 상한과 비교하지 못했습니다. 이 세대원 수에 대한 상한을 저희가 갖고 있지 않습니다.",
    "Work through the open items on step 5. Each one says what to send.":
      "5단계의 남은 항목을 하나씩 처리해 주세요. 무엇을 보내면 되는지 각 항목에 적혀 있습니다.",

    // R26: 지역 비교 패널 — 추정 거부는 그대로 두고, 풀 수 있는 사람을 이름으로 댄다.
    "We cannot line this household up against another region. The figures above are not compared against a frozen limit for a household size we hold, and HUD does not publish these limits for households of more than eight people. We will not estimate one.":
      "이 세대를 다른 지역과 나란히 놓을 수 없습니다. 위의 수치는 저희가 가진 세대원 수 상한과 비교된 것이 아니고, HUD 는 8인 초과 세대에 대해 이 상한을 공표하지 않습니다. 저희가 추정하지는 않습니다.",
    "Ask your housing worker for the published limit for your household size. They hold the tables this page will not guess from.":
      "세대원 수에 해당하는 공표된 상한은 주택 담당자에게 물어보세요 — 이 페이지가 짐작하지 않는 그 표를, 담당자는 갖고 있습니다.",

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

    // ── app.js: 점검 목록 화면 ────────────────────────────────────────────────
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
    "Take your packet": "신청 서류 묶음 받기",
    "This packet is the file you hand to the housing office. Inside is a cover sheet a person can read, plus records in machine form that their systems can check. You do not need to open the technical files.":
      "이 서류 묶음은 주택 사무소에 직접 건네는 파일입니다. 안에는 사람이 읽을 수 있는 표지 한 장과, 사무소 시스템이 확인할 수 있는 기계용 기록이 함께 들어 있습니다. 기술 파일은 열어 볼 필요가 없습니다.",
    "Nothing is sent anywhere.": "어디로도 전송되지 않습니다.",
    "This button writes a file to your own device and nothing else. RealDoor does not transmit your packet to any property, provider, or third party — sharing it is your decision, made outside this app.":
      "이 버튼은 당신의 기기에 파일 하나를 쓸 뿐입니다. RealDoor 는 서류 묶음을 어떤 임대인·기관·제3자에게도 보내지 않습니다. 공유할지 말지는 이 앱 바깥에서 당신이 정합니다.",
    "The packet contains what your documents show, what is still missing or expired, and every open question below. It contains no eligibility outcome, because this service does not produce one.":
      "서류 묶음에는 당신의 서류가 보여주는 것, 아직 없거나 기한이 지난 것, 그리고 아래의 모든 남은 물음이 담깁니다. 자격에 대한 결론은 담기지 않습니다. 이 서비스가 그런 결론을 만들지 않기 때문입니다.",
    "Download my readiness packet": "내 준비 상태 신청 서류 묶음 내려받기",

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
      "말하지 않은 것은 따로 세며, 틀린 답으로 채점하지 않습니다.",
    "The pack's 24 tests are 12 distinct hostile inputs, each present twice. We report 24 runs but only 12 independent probes. Detectors are keyword and canary based: a pass is evidence, not proof.":
      "팩의 24개 시험은 서로 다른 적대적 입력 12개가 각각 두 번씩 들어 있는 것입니다. 우리는 24회 실행을 보고하지만 독립적인 시험은 12개뿐입니다. 탐지기는 키워드와 카나리아 기반입니다. 통과는 증거이지 증명이 아닙니다.",
    "Compared against pack/starter/src/calculate.py, the organizer's own reference implementation, imported directly rather than copied.":
      "주최 측 자체 참조 구현인 pack/starter/src/calculate.py 와 대조했습니다. 베끼지 않고 직접 import 했습니다.",
    "Re-verifying each cited rule against its live source URL is not wired yet. Reported as zero rather than assumed.":
      "인용한 각 규칙을 원문 URL 과 다시 대조하는 작업은 아직 연결되어 있지 않습니다. 됐다고 가정하지 않고 0 으로 보고합니다.",
    "Incomplete means axe declined to judge, not that a check passed. Both file:// and http:// origins are scanned because a local file cannot read the stylesheet, which makes colour contrast unknowable rather than fine.":
      "incomplete 는 검사를 통과했다는 뜻이 아니라 axe 가 판단을 보류했다는 뜻입니다. 로컬 파일은 스타일시트를 읽을 수 없어 색 대비를 알 수 없게 되므로, file:// 과 http:// 두 주소를 모두 검사합니다.",
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

    // ══ 아래는 화면 본문이다 ═══════════════════════════════════════════════
    // 위쪽 사전이 껍데기(머리말·버튼·표 제목)를 옮긴다면, 이 아래는 세입자가
    // 실제로 읽는 문장이다. 대부분 api/plain.py 가 만들고 API 응답으로 실려 온다.
    // 영어 원문은 미국 공공서비스 문체(짧은 문장·2인칭·행동 지시)이므로, 한국어도
    // 관공서 안내문의 좋은 쪽 — 짧은 문장, 존댓말, 분명한 행동 — 으로 옮긴다.
    // 직역하지 않는다. 한 영어 문장이 두 가지를 말하면 한국어에서는 두 문장으로 쪼갠다.
    //
    // 날짜·금액·문서 이름이 문장 안에 박혀 정확 매칭이 안 되는 것들은 여기가 아니라
    // 아래 RULES 에서 정규식으로 잡는다.

    // ── api/plain.py — 준비 상태 머리말 ──────────────────────────────────────────
    "Your paperwork is ready for a person to read": "서류가 사람이 검토할 준비를 마쳤습니다",
    "We have what we need to hand your file to a housing worker. They will read it and decide what happens next. This does not tell you what they will say. It means nothing is missing, out of date, or unclear enough to stop them starting.":
      "주택 담당자에게 서류를 넘기는 데 필요한 것이 모두 있습니다. 담당자가 서류를 읽고 다음 절차를 정합니다. 담당자가 어떤 결정을 내릴지는 이 화면이 말하지 않습니다. 빠진 서류도, 기한이 지난 서류도, 검토를 시작하지 못할 만큼 불분명한 서류도 없다는 뜻입니다.",
    "You do not need to send anything else right now. Wait for the housing worker to come back to you.":
      "지금 더 보내실 서류는 없습니다. 주택 담당자의 연락을 기다려 주세요.",
    "Your file needs a few things before a person can read it": "사람이 검토하기 전에 몇 가지가 더 필요합니다",
    "Some papers are missing, out of date, or do not agree with each other. We list each one below, with what to do about it. None of this is a finding about you. It is about the paperwork. You can fix paperwork.":
      "빠졌거나, 기한이 지났거나, 서로 맞지 않는 서류가 있습니다. 아래에 하나씩, 무엇을 하면 되는지와 함께 적었습니다. 이것은 당신에 대한 판단이 아닙니다. 서류에 대한 것이고, 서류는 고칠 수 있습니다.",
    "Work through your list below. Each item says exactly what to send or who to ask.":
      "아래 목록을 하나씩 처리해 주세요. 항목마다 무엇을 보내야 하는지, 누구에게 요청해야 하는지 적혀 있습니다.",

    // ── api/plain.py — 서류를 갖췄을 때 / 빠졌을 때 ──────────────────────────────────
    "You do not need to do anything about this one.": "이 항목은 따로 하실 일이 없습니다.",
    "Fill in your application form and upload it.": "신청서를 작성해서 올려 주세요.",
    "Upload your two most recent pay stubs.": "가장 최근 급여명세서 2장을 올려 주세요.",
    "Ask your employer for a signed letter confirming your job, then upload it.":
      "고용주에게 재직 사실을 확인하는 서명된 증명서를 받아 올려 주세요.",
    "Upload the award letter for the benefit you get.": "받고 계신 급여의 수급 결정 통지서를 올려 주세요.",
    "Upload your most recent earnings statement from the app you work for.": "일하시는 플랫폼에서 발급한 가장 최근 수입 명세서를 올려 주세요.",
    "Upload your bank statements, your earnings records from the app you work for, or a 1099 form covering the same dates.":
      "같은 기간의 은행 거래내역, 일하시는 플랫폼의 수입 기록, 또는 1099 양식을 올려 주세요.",

    // ── api/plain.py — 긱 수입 ───────────────────────────────────────────────
    "Nothing in your file backs up your gig earnings": "긱 수입을 뒷받침하는 자료가 없습니다",

    // ── api/plain.py — 정정이 계산에 쓰였을 때 / 쓰이지 않았을 때 ──────────────────────────
    "We used the number you corrected": "고치신 숫자를 계산에 썼습니다",
    "Open the document on screen and check your figure against the page one more time. Tell us if anything still looks wrong.":
      "화면에서 문서를 열어 고치신 숫자를 다시 한번 대조해 주세요. 이상한 점이 있으면 알려 주세요.",
    "Tell us which amount is right, or add a stub that shows your usual pay. If the hours or the hourly rate are also wrong, correct those too.":
      "어느 금액이 맞는지 알려 주시거나, 평소 급여가 나온 명세서를 추가해 주세요. 근무시간이나 시급도 틀렸다면 함께 고쳐 주세요.",

    // ── api/plain.py — 급여명세서 충돌 ───────────────────────────────────────────
    "We could not work out your regular pay": "정기 급여가 얼마인지 알아내지 못했습니다",
    "Ask your employer which stub shows your normal pay, or upload a stub that shows a normal week. Then upload it here.":
      "어느 명세서가 평소 급여를 보여주는지 고용주에게 물어보시거나, 평소와 같은 한 주가 담긴 명세서를 받으세요. 그런 다음 여기에 올려 주세요.",
    "Your employer's letter and your pay stubs do not agree": "재직증명서와 급여명세서가 서로 맞지 않습니다",
    "Ask your employer which figure is right. If the letter is wrong, ask them for a corrected one and upload it.":
      "어느 금액이 맞는지 고용주에게 확인해 주세요. 증명서가 틀렸다면 정정된 증명서를 받아 올려 주세요.",
    "Ask your employer to check this stub. If it is wrong, ask for a corrected one and upload it.":
      "고용주에게 이 명세서를 확인해 달라고 요청해 주세요. 틀렸다면 정정된 명세서를 받아 올려 주세요.",
    "Your pay stubs show different totals": "급여명세서마다 총액이 다릅니다",
    "Ask your employer whether the extra pay is a regular part of your wages, then tell us what they say.":
      "그 추가 급여가 정기적으로 받는 급여인지 고용주에게 확인하시고, 답을 알려 주세요.",
    "Your pay stubs do not agree with each other": "급여명세서끼리 서로 맞지 않습니다",
    "The totals on your pay stubs are not the same. We used the stub whose hours and hourly rate add up to its own total. We left the difference out of your yearly figure, because we cannot tell whether it comes every time.":
      "급여명세서의 총액이 서로 다릅니다. 근무시간과 시급이 자기 총액과 맞아떨어지는 명세서를 썼습니다. 차액은 연 소득에서 뺐습니다. 매번 나오는 금액인지 알 수 없기 때문입니다.",
    "Ask your employer which stub shows your normal pay, then tell us what they say.":
      "어느 명세서가 평소 급여를 보여주는지 고용주에게 확인하시고, 답을 알려 주세요.",

    // ── api/plain.py — 추적 가능성 ─────────────────────────────────────────────
    "We could not show a housing worker where one of your numbers came from": "숫자 하나가 어디에서 나왔는지 주택 담당자에게 보여줄 수 없었습니다",
    "Open your document on screen and check the number against the page. Tell us if it is right, or correct it.":
      "화면에서 문서를 열어 숫자를 문서와 대조해 주세요. 맞으면 맞다고 알려 주시고, 틀렸으면 고쳐 주세요.",
    "We could not show where your pay figure came from": "급여 금액이 어디에서 나왔는지 보여줄 수 없었습니다",
    "Open your document on screen and confirm the amount against the page, or upload a clearer copy.":
      "화면에서 문서를 열어 금액을 문서와 대조해 확인해 주시거나, 더 선명한 사본을 올려 주세요.",
    "We could not read a pay amount in your file": "제출하신 서류에서 급여 금액을 읽지 못했습니다",
    "Open your document on screen and type the amount in yourself, or upload a clearer copy.":
      "화면에서 문서를 열어 금액을 직접 입력하시거나, 더 선명한 사본을 올려 주세요.",

    // ── api/plain.py — 이름·소득·세대원 수 ────────────────────────────────────────
    "The papers in your file do not all show the same name": "서류마다 적힌 이름이 다릅니다",
    "Some of your documents carry one name and some carry another. That can happen for ordinary reasons, such as a married name, a shortened first name, or a typing mistake by whoever wrote the document. We cannot tell which it is, so we are asking rather than deciding.":
      "일부 서류에는 한 이름이, 다른 서류에는 다른 이름이 적혀 있습니다. 혼인 후 성이 바뀌었거나, 이름을 줄여 적었거나, 서류를 작성한 쪽에서 잘못 적는 등 흔한 이유로도 생길 수 있습니다. 어느 쪽인지 저희는 알 수 없으므로, 판단하지 않고 여쭙니다.",
    "Tell us which name is yours. If a document has the wrong name on it, ask whoever issued it for a corrected copy.":
      "어느 이름이 본인 이름인지 알려 주세요. 어떤 서류에 잘못된 이름이 적혀 있다면, 발급한 곳에 정정본을 요청해 주세요.",
    "We could not work out a yearly income from your papers": "제출하신 서류로는 연 소득을 계산하지 못했습니다",
    "None of the documents in your file gave us a pay amount we could rely on. This is not a finding about your money. It means the papers we have do not settle the figure, so we did not invent one.":
      "서류 어디에서도 믿고 쓸 만한 급여 금액을 얻지 못했습니다. 이것은 당신의 소득에 대한 판단이 아닙니다. 가지고 있는 서류가 금액을 확정해 주지 못한다는 뜻이며, 그래서 금액을 지어내지 않았습니다.",
    "Upload your two most recent pay stubs. If you get benefits or gig income, upload the award letter or the earnings statement as well.":
      "가장 최근 급여명세서 2장을 올려 주세요. 수급 급여나 긱 수입이 있다면 수급 결정 통지서나 수입 명세서도 함께 올려 주세요.",
    "We do not have an income limit for a household of your size": "이 세대원 수에 해당하는 소득 기준액이 없습니다",
    "The rules let us use one official table. It covers households of one to eight people, and yours is larger. A larger limit does exist, but it sits outside the table this project froze, so we will not take a number from anywhere else. We would rather tell you we are missing it than show you a figure we cannot source.":
      "규칙상 쓸 수 있는 공식 표는 하나입니다. 그 표는 1인부터 8인 세대까지만 담고 있는데, 이 세대는 그보다 큽니다. 더 큰 세대의 기준액도 존재하지만, 이 프로젝트가 동결한 표 바깥에 있습니다. 그래서 다른 곳에서 숫자를 가져오지 않습니다. 출처를 댈 수 없는 숫자를 보여드리느니, 없다고 말씀드리는 편을 택합니다.",
    "Ask your housing worker for the published income limit for a household of your size. They can add it and the comparison will run.":
      "이 세대원 수에 해당하는 공표된 소득 기준액을 주택 담당자에게 요청해 주세요. 담당자가 입력하면 비교가 진행됩니다.",
    "The rules let us use one official table. It covers households of one to eight people. A limit for a larger household does exist, but it sits outside the table this project froze, so we will not take a number from anywhere else.":
      "규칙상 쓸 수 있는 공식 표는 하나입니다. 그 표는 1인부터 8인 세대까지만 담고 있습니다. 더 큰 세대의 기준액도 존재하지만, 이 프로젝트가 동결한 표 바깥에 있습니다. 그래서 다른 곳에서 숫자를 가져오지 않습니다.",
    "Ask your housing worker for the published limit for a household of your size. They can add it and the comparison will run.":
      "이 세대원 수에 해당하는 공표된 기준액을 주택 담당자에게 요청해 주세요. 담당자가 입력하면 비교가 진행됩니다.",
    "We could not tell how many people are in your household": "세대원이 몇 명인지 알 수 없었습니다",
    "The income limit depends on how many people live with you. We could not read that number from your application form, so we could not look up your limit.":
      "소득 기준액은 함께 사는 사람 수에 따라 달라집니다. 신청서에서 그 숫자를 읽지 못해, 기준액을 찾지 못했습니다.",
    "Tell us how many people live in your household, counting yourself.": "본인을 포함해 몇 분이 함께 사시는지 알려 주세요.",

    // ── api/plain.py — 지급 주기와 비교 ──────────────────────────────────────────
    "We could not tell how often you are paid": "급여를 얼마나 자주 받으시는지 알 수 없었습니다",
    "Tell us how often you are paid, or upload a pay stub that says it on the page.":
      "급여를 얼마나 자주 받으시는지 알려 주시거나, 지급 주기가 적힌 급여명세서를 올려 주세요.",
    "Your pay schedule is not one we can convert": "이 지급 주기는 연 소득으로 환산할 수 없습니다",
    "We can turn five pay schedules into a yearly figure: weekly, every two weeks, twice a month, monthly and once a year. Your document names a different one. We will not invent a way to convert it, because the multiplier would be ours rather than the official one.":
      "연 소득으로 환산할 수 있는 지급 주기는 다섯 가지입니다. 주급, 2주마다, 월 2회, 월급, 연 1회입니다. 제출하신 문서에는 그 밖의 주기가 적혀 있습니다. 환산 방법을 새로 만들지는 않습니다. 그렇게 하면 공식 배수가 아니라 저희가 정한 배수가 되기 때문입니다.",
    "Ask your housing worker to convert this pay schedule into a yearly figure. They can enter it and the rest will follow.":
      "이 지급 주기를 연 소득으로 환산해 달라고 주택 담당자에게 요청해 주세요. 담당자가 입력하면 나머지는 이어서 진행됩니다.",
    "We could not compare your income with the limit": "소득을 기준액과 비교하지 못했습니다",
    "The comparison needs a yearly income figure for you, and we do not have one yet. We list the reasons above. Once you clear those, the comparison runs on its own.":
      "비교하려면 연 소득 금액이 있어야 하는데, 아직 없습니다. 그 이유는 위에 적어 두었습니다. 그 항목들이 해결되면 비교는 저절로 진행됩니다.",
    "Work through the other items on your list first. Each one says what to send.":
      "목록의 다른 항목들을 먼저 처리해 주세요. 항목마다 무엇을 보내야 하는지 적혀 있습니다.",

    // ── api/plain.py — 물음에 대한 응답과 거부 ──────────────────────────────────────
    "We cannot tell you whether you will get the home": "집을 얻으실 수 있는지는 알려 드릴 수 없습니다",
    "This service does not determine eligibility and will not label any person. What we do is get your paperwork ready and check the numbers in it. A trained housing worker is the one who makes that call, and only they can make it. We can tell you what your papers say, what the income limit is for your household size, and how the two compare.":
      "이 서비스는 자격을 판정하지 않으며, 어떤 사람에게도 딱지를 붙이지 않습니다. 저희가 하는 일은 서류를 검토 받을 수 있게 정리하고, 그 안의 숫자를 확인하는 것입니다. 그 판단은 훈련받은 주택 담당자만 할 수 있습니다. 저희는 서류에 무엇이 적혀 있는지, 이 세대원 수의 소득 기준액이 얼마인지, 그 둘이 어떻게 비교되는지는 알려 드릴 수 있습니다.",
    "Ask us what your yearly income comes to, what the limit is for your household size, or what is still missing from your file.":
      "연 소득이 얼마인지, 이 세대원 수의 기준액이 얼마인지, 또는 서류에서 아직 무엇이 빠졌는지 물어보세요.",
    "We can only talk about your own file": "본인 서류에 대해서만 말씀드릴 수 있습니다",
    "This session holds your documents and nobody else's. We never show one person's papers to another person. That holds even if you ask us directly.":
      "이 세션에는 본인의 서류만 들어 있고 다른 사람의 서류는 없습니다. 한 사람의 서류를 다른 사람에게 보여주지 않습니다. 직접 요청하셔도 마찬가지입니다.",
    "Ask about your own documents. If you are helping someone else, open their own session with them.":
      "본인 서류에 대해 물어보세요. 다른 분을 돕고 계신다면, 그분과 함께 그분의 세션을 여세요.",
    "We read that as text in your document, not as an order": "그 문장은 지시가 아니라 문서에 적힌 글로 읽었습니다",
    "Some documents contain sentences that try to tell this service what to do. We store that text and show it to you, and it changes nothing. The sums and the checks in this service are fixed code. No sentence in any document can reach them.":
      "어떤 문서에는 이 서비스에 무엇을 하라고 지시하려는 문장이 들어 있습니다. 저희는 그 문장을 저장해 보여드릴 뿐, 그것으로 달라지는 것은 없습니다. 이 서비스의 계산과 점검은 고정된 코드입니다. 문서에 적힌 어떤 문장도 거기에 닿지 않습니다.",
    "Ask about a rule, a document you need, or one of the numbers we worked out.":
      "규칙이나, 필요한 서류, 또는 저희가 계산한 숫자에 대해 물어보세요.",
    "We do not work out anything about who you are": "당신이 어떤 사람인지는 전혀 추론하지 않습니다",
    "We never try to tell your disability, your immigration status, or anything like them from a document. There is no step in this service that does that. The income sum reads a short, fixed list of pay fields and nothing else.":
      "문서에서 장애 여부나 체류 자격 같은 것을 알아내려 시도하지 않습니다. 이 서비스에는 그런 단계가 아예 없습니다. 소득 계산은 정해진 급여 항목 몇 가지만 읽고, 그 밖에는 아무것도 읽지 않습니다.",
    "Ask about a pay amount, a document you need, or the income limit for your household size.":
      "급여 금액이나, 필요한 서류, 또는 이 세대원 수의 소득 기준액에 대해 물어보세요.",
    "We cannot tell you which homes are free right now": "지금 어느 집이 비어 있는지는 알려 드릴 수 없습니다",
    "The housing data behind this service is a fixed snapshot. It lists buildings and units. It does not carry waiting lists, and it does not say what is open today. Openings change daily and the property holds that information, not us.":
      "이 서비스가 쓰는 주택 데이터는 고정된 스냅숏입니다. 건물과 호실 목록은 있지만, 대기자 명단은 없고 오늘 무엇이 비어 있는지도 적혀 있지 않습니다. 공실은 날마다 바뀌고, 그 정보는 저희가 아니라 해당 임대 사업장이 가지고 있습니다.",
    "Call the property's management office, or your local housing agency, and ask what is open now.":
      "해당 임대 사업장의 관리사무소나 거주 지역 주택 담당 기관에 전화해 지금 무엇이 비어 있는지 물어보세요.",
    "We only use income limits we can point at": "출처를 짚을 수 있는 소득 기준액만 씁니다",
    "The limits in this service come from one fixed official table, and we show you where each figure comes from. We do not use a figure remembered from an earlier year. If a different figure applies to you, we need the document it comes from before we can use it.":
      "이 서비스의 기준액은 고정된 공식 표 하나에서 가져오고, 각 금액이 어디에서 왔는지 함께 보여드립니다. 예전 연도에서 기억해 둔 숫자는 쓰지 않습니다. 다른 금액이 적용된다면, 그 금액이 실린 문서를 받아야 쓸 수 있습니다.",
    "Send the document that carries the other figure. We will either cite it or tell you why we cannot use it.":
      "다른 금액이 실린 문서를 보내 주세요. 그 문서를 인용하거나, 왜 쓸 수 없는지 말씀드리겠습니다.",
    "A number we cannot point at is one we will not use in your file": "어디에서 나왔는지 짚을 수 없는 숫자는 서류에 쓰지 않습니다",
    "Every figure in your file has to trace back to a spot on a page. A housing worker has to be able to look at it. When we cannot show where a number came from, we hold it aside instead of showing it to you as a finding.":
      "서류의 모든 숫자는 문서의 한 위치까지 되짚을 수 있어야 합니다. 주택 담당자가 그 자리를 직접 볼 수 있어야 하기 때문입니다. 숫자가 어디에서 나왔는지 보여드릴 수 없을 때는, 확인된 내용인 것처럼 보여드리지 않고 따로 빼 둡니다.",
    "An out-of-date paper holds up your whole file": "기한이 지난 서류 하나가 전체 검토를 멈춥니다",
    "When two numbers disagree, we tell you instead of picking one": "두 숫자가 어긋나면, 하나를 고르지 않고 알려 드립니다",
    "If the parts of a pay stub do not add up to its own total, the numbers are in conflict. We report the gap rather than smoothing it into a tidy figure. If no stub adds up at all, we produce no yearly figure, because choosing one of two numbers with nothing to separate them would be a guess.":
      "급여명세서의 각 항목이 자기 총액과 맞아떨어지지 않으면, 그 숫자들은 서로 어긋난 것입니다. 저희는 그 차이를 깔끔한 숫자로 다듬지 않고 그대로 알려 드립니다. 어느 명세서도 맞아떨어지지 않으면 연 소득 금액을 내지 않습니다. 가를 근거가 없는 두 숫자 중 하나를 고르는 것은 짐작이기 때문입니다.",
    "Ask your employer which figure is your normal pay, or ask them for a corrected stub, then upload it.":
      "어느 금액이 평소 급여인지 고용주에게 물어보시거나, 정정된 명세서를 받아 올려 주세요.",
    "A marker landed off your page, so we will not trust it": "표시가 문서 바깥에 찍혀서, 그 값은 믿지 않습니다",
    "We draw a box around every number we read so you can see where it came from. A box that falls outside the page points at nothing you could look at. We treat the number it carries as unusable rather than showing it to you.":
      "저희는 읽어낸 숫자마다 문서에 네모를 그려서 어디에서 나왔는지 보이게 합니다. 문서 바깥에 놓인 네모는 볼 수 있는 자리를 가리키지 못합니다. 그런 네모가 달린 숫자는 보여드리지 않고 쓸 수 없는 것으로 처리합니다.",
    "Read the number off your document yourself and type it in, or upload a clearer copy of the page.":
      "문서에서 숫자를 직접 읽어 입력하시거나, 그 쪽의 더 선명한 사본을 올려 주세요.",
    "What you write on a form is not the same as proof": "신청서에 적어 넣은 숫자는 증빙과 다릅니다",
    "A figure you write on your own application form is your own statement. It is not evidence from an employer or a bank. We do not turn one into the other. Your own figure does not go into the income sum at all.":
      "본인이 신청서에 적은 금액은 본인의 진술입니다. 고용주나 은행에서 나온 증빙이 아닙니다. 저희는 진술을 증빙으로 바꾸지 않습니다. 본인이 적은 금액은 소득 계산에 아예 들어가지 않습니다.",
    "Upload a letter from your employer, your bank statements, your earnings records from the app you work for, or a 1099 form covering the same dates.":
      "고용주의 증명서, 은행 거래내역, 일하시는 플랫폼의 수입 기록, 또는 같은 기간의 1099 양식을 올려 주세요.",

    // ── api/plain.py — 평문 문구가 아직 없을 때 ─────────────────────────────────────
    "Something in your file needs a person to look at it": "서류에 사람이 봐야 할 것이 있습니다",
    "We found something we have not yet learned how to explain in plain words. We would rather say that than show you wording we made up. The exact technical wording is kept with this message.":
      "저희가 아직 쉬운 말로 설명하는 법을 익히지 못한 것을 찾았습니다. 지어낸 문구를 보여드리느니 그렇게 말씀드립니다. 정확한 기술 문구는 이 안내와 함께 보관되어 있습니다.",
    "Ask your housing worker to look at this item with you. The technical note next to it tells them what we found.":
      "이 항목을 주택 담당자와 함께 살펴봐 주세요. 옆에 있는 기술 설명이 담당자에게 무엇을 찾았는지 알려 줍니다.",

    // ── api/plain.py — 이렇게 쓴 이유 (precision_note) ──────────────────────────
    "We say the extra pay was 'not counted across the whole year' rather than 'ignored'. It was neither ignored nor annualized: it is reported and set aside. Calling it ignored would understate what we did with it.":
      "추가 급여를 “무시했다”가 아니라 “한 해 전체에 곱하지 않았다”고 적었습니다. 무시한 것도 아니고 연 환산한 것도 아닙니다. 보고하되 따로 빼 둔 것입니다. 무시했다고 하면 실제로 한 일을 축소해 말하는 것이 됩니다.",
    "The amount is still counted. We say so plainly rather than implying the money was discounted, because withholding it would distort the total in the other direction.":
      "금액은 그대로 계산에 넣었습니다. 돈을 깎은 것처럼 들리게 하지 않고 그 사실을 그대로 적습니다. 빼 버리면 합계가 반대 방향으로 왜곡되기 때문입니다.",
    "We say 'we left this stub out', not 'we ignored your change'. The change is stored and shown to the reviewer; what it did not do is move the total. Saying we ignored it would be false, and saying it was applied would be worse.":
      "“고치신 내용을 무시했다”가 아니라 “이 명세서를 빼 두었다”고 적었습니다. 고치신 내용은 저장되어 검토자에게 보입니다. 다만 합계를 움직이지 못했을 뿐입니다. 무시했다고 하면 거짓이고, 반영했다고 하면 더 나쁩니다.",
    "'We do not have a limit for your size' is the truth. 'There is no limit for your size' would be false — one exists, we are just not allowed to source it from outside the frozen table.":
      "“이 세대원 수의 기준액을 저희가 가지고 있지 않다”가 사실입니다. “이 세대원 수에는 기준액이 없다”는 거짓입니다 — 기준액은 존재하고, 다만 동결된 표 바깥에서 가져오는 것이 허용되지 않을 뿐입니다.",
    "This says a person can start reading. It deliberately does not say the renter will get a home, and it must never be shortened to anything that sounds like it does. The machine status name is kept in `detail` so the exact term stays retrievable.":
      "사람이 검토를 시작할 수 있다는 뜻입니다. 세입자가 집을 얻게 된다는 뜻은 의도적으로 담지 않았고, 그렇게 들릴 만한 말로 줄여서도 안 됩니다. 기계가 쓰는 상태 이름은 detail 에 남겨 두어 정확한 용어를 다시 찾아볼 수 있게 했습니다.",
    "'Needs a few things' describes the packet. It must not be read as a judgement about the person, which is why the body says so outright.":
      "“몇 가지가 더 필요하다”는 신청 서류 묶음을 설명하는 말입니다. 사람에 대한 평가로 읽혀서는 안 되며, 그래서 본문에서 그 점을 대놓고 말합니다.",

    // ── app.js — 근거 화면과 남은 물음 ─────────────────────────────────────────────
    "Try one of these": "이 중 하나를 눌러 보세요",
    "Show the box coordinates column": "근거 위치 좌표 열 보기",
    "The box coordinates behind each highlight can be shown as a column.": "각 강조 표시 뒤에 있는 근거 위치 좌표를 열로 펼쳐 볼 수 있습니다.",
    "Raised as": "제기된 코드",
    "Resolved by": "이렇게 하면 풀립니다",
    "a housing professional answers this, or the question is rephrased to name the rule it is about":
      "주택 전문가가 답하거나, 어떤 규칙에 대한 물음인지 이름을 넣어 다시 물으면 됩니다",
    "This service must never approve, deny, score, rank or prioritise. The response was withheld.":
      "이 서비스는 승인·거절·점수·순위·우선순위를 매겨서는 안 됩니다. 그래서 응답을 내보내지 않았습니다.",

    // ── app.js — 인용의 근거 기관과 위치 ────────────────────────────────────────────
    "hackathon simulation": "해커톤 시뮬레이션",
    "official hud": "HUD 공식 자료",
    "Frozen challenge convention": "과제가 동결한 기준",
    "Human-decision boundary": "사람이 판단하는 경계",
    "FY 2026 effective date notice": "2026 회계연도 시행일 고시",
    "Untrusted-document rule": "문서를 신뢰하지 않는 규칙",

    // ── app.js — 계산과 근거 항목 이름 ─────────────────────────────────────────────
    "annualized gig income": "연환산 긱 소득",
    "gross receipts": "총 수입",
    "statement month": "명세서 해당 월",

    // ── app.js — 우리 성적표: 구역 제목 ────────────────────────────────────────────
    "Plain wording, measured on the message layer": "평문 문구 — 메시지 계층에서 측정",
    "Plain wording, measured on the rendered screen": "평문 문구 — 실제 그려진 화면에서 측정",
    "intent router": "의도 라우터",

    // ── app.js — 우리 성적표: 측정 항목 이름 ─────────────────────────────────────────
    "exact match": "정확히 일치",
    "selective accuracy": "선택적 정확도",
    "fields total": "전체 항목 수",
    "bbox evaluated": "근거 위치 평가 건수",
    "bbox iou gt 0 5": "근거 위치 IoU 0.5 초과",
    "bbox iou mean": "근거 위치 IoU 평균",
    "gold sha256": "정답 데이터 sha256",
    "total tests": "전체 시험 수",
    "failed test ids": "실패한 시험 id",
    "distinct inputs": "서로 다른 입력 수",
    "agree with organizer reference": "주최 측 기준 구현과 일치",
    "rules in corpus": "규칙 묶음의 규칙 수",
    "verified against live source": "원문과 대조해 확인한 수",
    "codes with plain wording": "평문 문구가 있는 코드 수",
    "situations with plain wording": "평문 문구가 있는 상황 수",
    "messages checked": "점검한 메시지 수",
    "renter facing strings": "세입자가 읽는 문장 수",
    "free of raw identifiers": "기계 식별자가 없는 비율",
    "uses second person per string": "2인칭을 쓴 비율 (문장 기준)",
    "uses second person per message": "2인칭을 쓴 비율 (메시지 기준)",
    "active voice best effort": "능동태 비율 (추정)",
    "problem messages carrying an action": "행동 지시가 붙은 문제 메시지 비율",
    "action gaps": "행동 지시를 못 단 항목",
    "actions needing a trained person": "훈련받은 사람이 해야 하는 행동",
    "household id leaks": "세대 id 유출",
    "households walked": "걸어 본 세대 수",
    "steps per household": "세대당 단계 수",
    "identifier patterns": "식별자 패턴 수",
    "visible machine identifiers": "화면에 보이는 기계 식별자",
    "visible machine identifiers by step": "단계별 화면에 보이는 기계 식별자",
    "screens needing older wording": "예전 문구가 필요한 화면",
    "plain wording gaps": "평문 문구가 없는 항목",
    "page errors": "페이지 오류",
    "known intents": "알고 있는 의도 수",
    "questions reaching the classifier": "분류기까지 간 질문 수",
    "cache hits": "캐시 적중 수",
    "cache hit rate": "캐시 적중률",
    "classifier said unknown": "분류기가 모른다고 한 수",
    "rejected label outside closed set": "기각 — 정해진 집합 밖의 이름",
    "rejected deterministic router disagreed": "기각 — 결정론적 라우터가 동의하지 않음",
    "rejected no anchor": "기각 — 근거 없음",
    "offline or uncached": "오프라인이거나 캐시에 없음",
    "anchor audit ok": "근거 점검 통과",
    "anchor audit detail": "근거 점검 상세",

    // ── app.js — 우리 성적표: 해설 ───────────────────────────────────────────────
    "file:// (offline, bundled fixtures — the state the submitted build opens in)":
      "file:// (오프라인, 번들된 고정 데이터 — 제출 빌드가 열리는 상태)",
    "Only 'problem_messages_carrying_an_action' is a requirement: WCAG 2.2 SC 3.3.3 Error Suggestion is Level AA, and it must read 1.0. Second person and active voice are Federal Plain Language Guidelines style goals we adopted voluntarily; the FPLG sets no reading-grade target and no sentence-length rule. SC 3.1.5 Reading Level is Level AAA and is not required at AA. The active-voice figure is a regex heuristic with documented blind spots, not a measurement of grammar. Readability is reported as two formulas plus their spread, per screen, on samples of at least 100 words, because a single per-string grade is not defensible.":
      "요구사항인 것은 problem_messages_carrying_an_action 하나뿐입니다. WCAG 2.2 SC 3.3.3 오류 정정 제안은 AA 등급이고 1.0 이어야 합니다. 2인칭과 능동태는 미국 연방 평이언어 지침(FPLG)의 문체 목표이며 저희가 자발적으로 채택한 것입니다. FPLG 는 읽기 등급 목표도, 문장 길이 규칙도 두지 않습니다. SC 3.1.5 읽기 수준은 AAA 등급이고 AA 에서는 요구되지 않습니다. 능동태 수치는 한계가 문서화된 정규식 어림값이지 문법을 측정한 것이 아닙니다. 읽기 쉬움은 화면마다 100 단어 이상 표본에 대해 공식 두 개와 그 차이로 보고합니다. 문장 하나하나에 등급을 매기는 것은 근거를 댈 수 없기 때문입니다.",
    "This is the DOM-level twin of the plain_language section above, and the two must be read together: that one measures whether the renter-facing wording is clean, this one measures whether it reaches the screen. Text inside a collapsed disclosure is not counted, because it is not visible — every machine code and every original message is still there, one click away. Household ids are counted separately and excluded, because the header picker names the file being read. This number is published, not gated: no target has been agreed for it, and the remaining count is concentrated on the evidence and calculation screens, where a document id is the subject of the row rather than an intrusion into a sentence.":
      "이것은 위 plain_language 구역의 DOM 판이며, 둘은 함께 읽어야 합니다. 위쪽은 세입자가 읽는 문구가 깨끗한지를 재고, 이쪽은 그 문구가 화면까지 도달하는지를 잽니다. 접힌 disclosure 안의 글자는 보이지 않으므로 세지 않습니다 — 모든 기계 코드와 원래 메시지는 클릭 한 번 아래에 그대로 있습니다. 세대 id 는 따로 세고 제외합니다. 머리말의 선택기가 지금 읽고 있는 파일의 이름을 말해 주기 때문입니다. 이 숫자는 게이트가 아니라 공개용입니다. 합의된 목표치가 없고, 남은 건수는 근거 화면과 계산 화면에 몰려 있습니다. 그곳에서는 문서 id 가 문장에 끼어든 것이 아니라 그 줄의 주어이기 때문입니다.",
    "The classifier returns one label from a closed set and never writes a sentence; every sentence a renter reads is still built by deterministic code. A label is only acted on after the deterministic router is asked again and agrees, so the classifier can point at existing answers but cannot create one. It is reached only when every deterministic layer is silent, which is why the graded question set does not touch it. Only the question text is sent; no document content or household data leaves this process. Counters are since process start, not since the pack was written. When the router is switched off these figures read not_run rather than zero-as-success.":
      "분류기는 정해진 집합에서 이름 하나를 돌려줄 뿐 문장을 쓰지 않습니다. 세입자가 읽는 모든 문장은 여전히 결정론적 코드가 만듭니다. 어떤 이름이든 결정론적 라우터에 다시 물어 동의를 받은 뒤에야 쓰이므로, 분류기는 이미 있는 답을 가리킬 수는 있어도 답을 새로 만들 수는 없습니다. 결정론적 계층이 모두 침묵할 때만 분류기에 닿기 때문에, 채점되는 질문 묶음은 여기에 닿지 않습니다. 보내는 것은 질문 글자뿐이며 문서 내용이나 세대 데이터는 이 프로세스를 벗어나지 않습니다. 계수기는 팩이 작성된 시점이 아니라 프로세스가 시작된 시점부터 셉니다. 라우터를 꺼 두면 이 수치들은 0 을 성공으로 보이게 하지 않고 not_run 으로 표시됩니다.",


    // ── api/selftest.py — 나가기 직전의 식별자 제거 ────────────────────────────
    "identifier patterns looked for": "찾아본 식별자 패턴",
    "questions scrubbed before sending": "보내기 전에 걸러 낸 질문 수",
    "questions with a redaction": "가려진 부분이 있는 질문 수",
    "identifiers replaced": "바꿔 넣은 식별자 수",
    "identifiers replaced by pattern": "패턴별로 바꿔 넣은 식별자 수",
    "redaction note": "식별자 제거에 대한 설명",
    "accepted": "받아들임",
    "timeouts": "시간 초과",
    "errors": "오류",
    "calls": "호출 수",
    "model": "모델",
    "enabled": "켜져 있는지",
    "Before a question is sent, shapes that are identifiers on sight — an email address, a phone number, a nine-digit number written as a social security number, a street address carrying a house number, a postal code that says it is one — are replaced with a placeholder such as [address removed]. Placeholders rather than deletions, so the sentence keeps its shape and the topic stays findable. This is not a personal-data filter and must not be read as one. A name, an employer, a school, a landlord — anything that is identifying only because of what the sentence means — is not caught here and is sent as typed. Catching those would require judging the sentence, and judging it would require sending it, which is the thing being avoided; that problem is unsolved here rather than solved quietly. A count of zero on this row means no known shape was found, not that the question carried nothing personal.":
      "질문을 보내기 전에, 보기만 해도 식별자인 모양 — 이메일 주소, 전화번호, 주민등록번호처럼 적힌 아홉 자리 숫자, 번지수가 붙은 도로명 주소, 스스로 우편번호라고 밝힌 번호 — 을 [address removed] 같은 자리표시자로 바꿉니다. 지우지 않고 자리표시자로 바꾸는 이유는, 문장의 모양이 유지되어야 무엇에 대한 질문인지 찾을 수 있기 때문입니다. 이것은 개인정보 필터가 아니며, 그렇게 읽어서도 안 됩니다. 이름, 직장, 학교, 임대인처럼 문장의 뜻 때문에 비로소 식별자가 되는 것은 여기서 걸리지 않고 입력하신 그대로 나갑니다. 그런 것까지 걸러 내려면 문장을 판단해야 하고, 판단하려면 문장을 보내야 하는데, 그것이야말로 피하려는 일입니다. 이 문제는 조용히 해결한 척하지 않고 해결되지 않은 채로 두었습니다. 이 줄의 값이 0 이라는 것은 알려진 모양이 발견되지 않았다는 뜻이지, 질문에 개인적인 내용이 없었다는 뜻이 아닙니다.",
    "The classifier returns one label from a closed set and never writes a sentence; every sentence a renter reads is still built by deterministic code. A label is only acted on after the deterministic router is asked again and agrees, so the classifier can point at existing answers but cannot create one. It is reached only when every deterministic layer is silent, which is why the graded question set does not touch it. Only the question text is sent; no document content or household data leaves this process. The question text is written by the renter, so recognisable identifier shapes are replaced before it is sent — see redaction_note for what that does and does not reach. Counters are since process start, not since the pack was written. When the router is switched off these figures read not_run rather than zero-as-success.":
      "분류기는 정해진 집합에서 이름 하나를 돌려줄 뿐 문장을 쓰지 않습니다. 세입자가 읽는 모든 문장은 여전히 결정론적 코드가 만듭니다. 어떤 이름이든 결정론적 라우터에 다시 물어 동의를 받은 뒤에야 쓰이므로, 분류기는 이미 있는 답을 가리킬 수는 있어도 답을 새로 만들 수는 없습니다. 결정론적 계층이 모두 침묵할 때만 분류기에 닿기 때문에, 채점되는 질문 묶음은 여기에 닿지 않습니다. 보내는 것은 질문 글자뿐이며 문서 내용이나 세대 데이터는 이 프로세스를 벗어나지 않습니다. 질문 글자는 세입자가 직접 쓰는 것이므로, 알아볼 수 있는 식별자 모양은 보내기 전에 바꿔 넣습니다 — 그것이 무엇까지 걸러 내고 무엇은 걸러 내지 못하는지는 “식별자 제거에 대한 설명”을 보세요. 계수기는 팩이 작성된 시점이 아니라 프로세스가 시작된 시점부터 셉니다. 라우터를 꺼 두면 이 수치들은 0 을 성공으로 보이게 하지 않고 not_run 으로 표시됩니다.",

    // ── app.js — 규칙 질문 화면의 안내 ───────────────────────────────────────
    "You do not need to include your name, address or phone number to ask about a rule.":
      "규칙에 대해 물으실 때 이름·주소·전화번호를 넣지 않으셔도 됩니다.",

    // 정적 빌드에서 꺼져 있는 질문 입력창의 안내. 1단계 업로드 패널과 같은 배치이므로
    // 어투도 같게 옮긴다 — 못 하는 것을 먼저 말하고, 그 다음에 무엇을 돌리면 되는지.
    // 판정 어휘("자격")는 쓰지 않는다. 지명·확인은 판정이 아니라 경로 선택이다.
    "This copy has no server, so it cannot answer a question you type":
      "이 사본에는 서버가 없어서, 직접 타이핑하신 질문에는 답할 수 없습니다",
    "The box below is where you write a question in your own words. Answering one is done by the rule handlers, which run on a server, so on this static build the box is switched off rather than hidden — the feature exists, this copy just has nothing to run it. Start the server and the same box becomes live:":
      "아래 칸은 직접 자기 말로 질문을 쓰는 곳입니다. 그 질문에 답하는 일은 서버에서 도는 규칙 처리기가 합니다. 이 화면은 정적 빌드라서 입력칸을 숨기지 않고 꺼 두었습니다. 기능이 없는 것이 아니라 이 사본에 그것을 돌릴 것이 없을 뿐입니다. 서버를 띄우면 같은 입력칸이 그대로 살아납니다:",
    "Then open http://127.0.0.1:8077 and return to step 3.":
      "그런 다음 http://127.0.0.1:8077 을 열고 3단계로 돌아오세요.",
    "Typing here is also the one place a model is involved. The deterministic router only knows a fixed set of phrasings; when you ask in wording it does not recognise, a classifier reads your question text and names one label out of the 21 intents this system can already answer, or none. That label is a nomination and nothing more — an anchor phrase for the named intent is added to your question, the deterministic router is asked again, and if it does not independently arrive at the same intent the nomination is discarded. The model never writes a sentence you read, and it cannot reach an answer the deterministic code could not reach on its own.":
      "여기에 타이핑하는 것이 모델이 관여하는 유일한 지점이기도 합니다. 결정론적 라우터는 정해진 표현만 알아봅니다. 그 라우터가 알아보지 못하는 말투로 물으시면, 분류기가 질문 글자를 읽고 이 시스템이 이미 답할 수 있는 21개 의도 중 하나를 지목하거나, 아무것도 지목하지 않습니다. 그 이름은 지명일 뿐입니다. 지목된 의도의 앵커 문구를 질문에 덧붙여 결정론적 라우터에 다시 묻고, 그 라우터가 스스로 같은 의도에 이르지 못하면 그 지명은 폐기됩니다. 모델은 여러분이 읽는 문장을 쓰지 않으며, 결정론적 코드가 스스로 도달할 수 없는 답에는 닿을 수 없습니다.",

    "currently English — activate for Korean": "현재 영어 — 누르면 한국어로 바뀝니다",

    // ── api/plain.py — 짧게 다시 쓰인 본문 중 데이터가 박히지 않은 것 ──────────
    // 사전은 RULES 보다 먼저 조회된다. 그래서 "Your stubs show different totals."
    // 처럼 위쪽 규칙의 `(.+)` 에 잘못 걸릴 수 있는 문장은 여기 정확히 적어 둔다 —
    // 규칙이 먼저 잡으면 "명세서에 적힌 금액은 different totals 입니다" 가 된다.
    "Your stubs show different totals. On no stub do the hours and the hourly rate settle which figure is your regular pay, so rather than guess we left your wages out of the yearly income figure.":
      "명세서마다 총액이 다릅니다. 어느 명세서에서도 근무시간과 시급이 정기 급여가 얼마인지를 확정해 주지 못했습니다. 그래서 짐작하는 대신, 임금을 연 소득 금액에서 빼 두었습니다.",
    "The totals on your pay stubs are not the same. We used the stub whose hours and hourly rate add up to its own total, and left the difference out of your yearly figure, because we cannot tell whether it comes every time.":
      "급여명세서마다 총액이 다릅니다. 근무시간과 시급이 그 명세서의 총액과 맞아떨어지는 명세서를 썼고, 차액은 연 소득에서 빼 두었습니다. 그 차액이 매번 나오는 것인지 알 수 없기 때문입니다.",
    "Some of your documents carry one name and some carry another. That happens for ordinary reasons, such as a married name or a typing mistake, and we cannot tell which it is, so we are asking rather than deciding.":
      "제출하신 서류 중 일부에는 한 이름이, 일부에는 다른 이름이 적혀 있습니다. 혼인 후 성이 바뀌었거나 오타가 났거나 하는 흔한 이유로 그럴 수 있는데, 어느 쪽인지 저희는 알 수 없습니다. 그래서 판단하지 않고 여쭤봅니다.",
    "None of the documents in your file gave us a pay amount we could rely on. That is not a finding about your money: the papers we have do not settle the figure, so we did not invent one.":
      "제출하신 서류 중 어느 것에서도 믿고 쓸 수 있는 급여 금액을 얻지 못했습니다. 이것은 당신의 소득에 대한 판단이 아닙니다. 저희가 가진 서류가 금액을 확정해 주지 못했을 뿐이고, 그래서 금액을 지어내지 않았습니다.",
    // ⚠ NO_FROZEN_THRESHOLD. 주어가 반드시 우리여야 한다. "기준액이 없다"는 거짓이다 —
    //   기준액은 존재하고, 우리에게 출처를 댈 수 있는 사본이 없을 뿐이다. 둘째 문장이
    //   그 구별을 지므로 빼지 않는다.
    "The one official table we are allowed to use covers households of one to eight people, and yours is larger. A limit for your size does exist; we simply do not have it, because we will not take a number from outside that table.":
      "저희가 쓸 수 있는 단 하나의 공식 표는 1인부터 8인까지의 세대를 담고 있는데, 이 세대는 그보다 큽니다. 이 세대 규모에 해당하는 기준액은 분명히 있습니다. 저희가 그것을 가지고 있지 않을 뿐이고, 그 표 바깥의 숫자를 가져다 쓰지는 않습니다.",
    "The income limit depends on how many people live with you, and we could not read that number from your application form.":
      "소득 기준액은 함께 사는 사람이 몇 명인지에 따라 달라지는데, 신청서에서 그 숫자를 읽어내지 못했습니다.",
    "We can turn five pay schedules into a yearly figure: weekly, every two weeks, twice a month, monthly and once a year. Your document names a different one, and we will not invent a multiplier of our own for it.":
      "연 소득으로 바꿀 수 있는 지급 주기는 다섯 가지입니다. 주급, 2주급, 월 2회, 월급, 연 1회입니다. 제출하신 서류에는 그와 다른 주기가 적혀 있는데, 그에 대해 저희가 임의로 곱하는 수를 만들지는 않습니다.",
    "Tell us how often you are paid: weekly, every two weeks, twice a month, monthly or once a year. Or upload a pay stub that says it on the page.":
      "급여를 얼마나 자주 받으시는지 알려 주세요. 주급, 2주급, 월 2회, 월급, 연 1회 중 하나입니다. 또는 그것이 적혀 있는 급여명세서를 올려 주세요.",
    "The comparison needs a yearly income figure for you, and we do not have one yet. Once you clear the reasons listed above, it runs on its own.":
      "비교를 하려면 연 소득 금액이 있어야 하는데, 아직 없습니다. 위에 적힌 사유들이 해소되면 비교는 저절로 실행됩니다.",

    // ── app.js — 1단계 올리기 패널 ─────────────────────────────────────────────
    // 이 패널은 로컬 서버가 떠 있을 때만 살아 있다. 정적 빌드에서는 숨기지 않고 꺼
    // 두므로, 꺼져 있을 때의 안내문도 번역 대상이다.
    "Upload a document of your own": "직접 가진 문서 올리기",
    "The household above is already loaded from the challenge pack. You can also read a document of your own here. It is read on its own, and it changes nothing in the household below.":
      "위의 세대는 과제 팩에서 이미 불러와 있습니다. 여기서는 직접 가진 문서를 따로 읽어 볼 수도 있습니다. 그 문서 하나만 놓고 읽으며, 아래 세대의 내용은 아무것도 바뀌지 않습니다.",
    "Synthetic documents only": "합성 문서만 올려 주세요",
    // 원문이 일부러 좁게 약속한 자리다. "절대 안전" 이나 "모든 개인정보" 같은 완전성
    // 어휘를 넣지 않는다. 마지막 문장(그래도 누구의 것도 아닌 문서가 가장 안전하다)이
    // 앞의 약속을 스스로 좁히는 자리이므로 반드시 남긴다.
    "Please upload made-up documents, not a real person's pay stub or benefit letter. What you upload is held in this session's memory only, is never written to disk, is never sent anywhere, and is never used to train anything — but the safest document to test with is still one that belongs to nobody.":
      "실제 사람의 급여명세서나 수급 통지서가 아니라, 지어낸 문서를 올려 주세요. 올리신 문서는 이번 세션의 메모리에만 있고, 디스크에 기록하지 않으며, 어디로도 보내지 않고, 무엇을 학습시키는 데도 쓰지 않습니다. 그래도 시험용으로 가장 안전한 문서는 누구의 것도 아닌 문서입니다.",
    "This copy has no server, so it cannot read a file you choose":
      "이 사본에는 서버가 없어서, 고르신 파일을 읽을 수 없습니다",
    "Reading a PDF is done by the extractor, which runs on a server. This page is the static build, so the controls below are switched off rather than hidden — the feature exists, this copy just has nothing to run it. Start the server and the same panel becomes live:":
      "PDF 를 읽는 일은 서버에서 도는 추출기가 합니다. 이 화면은 정적 빌드라서, 아래 조작부를 숨기지 않고 꺼 두었습니다. 기능이 없는 것이 아니라 이 사본에 그것을 돌릴 것이 없을 뿐입니다. 서버를 띄우면 같은 패널이 그대로 살아납니다:",
    "Then open http://127.0.0.1:8077 and return to step 1.":
      "그런 다음 http://127.0.0.1:8077 을 열고 1단계로 돌아오세요.",
    "Uploading needs the server, because reading a PDF is done by the extractor rather than by this page.":
      "올리기는 서버가 있어야 합니다. PDF 를 읽는 일은 이 화면이 아니라 추출기가 하기 때문입니다.",

    "What kind of document is this?": "어떤 종류의 문서입니까?",
    "Choose the kind of document…": "문서 종류를 고르세요…",
    // typeWords(): document_type 의 밑줄을 공백으로 바꾼 것. 나머지 넷은 위쪽
    // "app.js: 문서 화면" 구역에 이미 있고, 이것 하나가 빠져 있었다.
    "benefit letter": "수급 통지서",
    "We have to ask. We work out the kind of document from the file's name, and we only recognise the naming the challenge pack uses — so for a file named anything else we would read no fields at all and could not tell you why.":
      "여쭤볼 수밖에 없습니다. 저희는 문서 종류를 파일 이름에서 알아내는데, 과제 팩이 쓰는 이름 규칙만 알아봅니다. 그래서 다른 이름의 파일이라면 항목을 하나도 읽지 못하면서 그 이유도 알려 드리지 못합니다.",
    // 파일 선택 버튼. app.js 가 브라우저 기본 컨트롤(브라우저 UI 언어로 그려진다)을
    // 치우고 <label> 을 버튼으로 그리면서 글자가 "PDF file" 에서 "Choose a PDF" 로
    // 바뀌었다. 옛 키도 남겨 둔다 — 걸리지 않는 키는 그냥 지나갈 뿐이다.
    "Choose a PDF": "PDF 고르기",
    "PDF file": "PDF 파일",
    "PDF only, up to 10 MB. A scanned page is fine — if there is no text in the file we read the picture instead, and say which of the two we did.":
      "PDF 만, 10 MB 까지. 스캔한 문서도 괜찮습니다. 파일에 글자가 없으면 그림 쪽을 읽고, 둘 중 어느 쪽으로 읽었는지 알려 드립니다.",
    "Read this document": "이 문서 읽기",
    "Reading…": "읽는 중…",
    "Reading the document…": "문서를 읽는 중…",
    "Reading the uploaded document…": "올리신 문서를 읽는 중…",
    "The uploaded document was not accepted.": "올리신 문서를 받아들이지 않았습니다.",

    // 거절 카드. 원문이 "could not" 이 아니라 "did not" 이다 — 못 읽은 것이 아니라
    // 읽지 않기로 한 것이므로 한국어도 주어를 우리로 두고 그렇게 적는다.
    "We did not read that file": "그 파일은 읽지 않았습니다",
    "Choose what kind of document this is first. We cannot work it out from the file name, and guessing is the one thing this service does not do.":
      "먼저 문서 종류를 골라 주세요. 파일 이름만으로는 알아낼 수 없고, 짐작하는 것은 이 서비스가 하지 않는 단 한 가지입니다.",
    "Choose a PDF file to read.": "읽을 PDF 파일을 골라 주세요.",
    "That document could not be read.": "그 문서를 읽지 못했습니다.",

    // ── 잠깐 멈춤(429). 거절 카드가 아니다 ────────────────────────────────────
    // 상한에 걸린 업로드는 **파일에 대한 판단이 아니다**. 서버가 문서를 열어 보지도
    // 않았으므로 "읽지 않았습니다" 라고 말하면 파일에 문제가 있다는 뜻이 되어 버린다.
    // 그래서 제목이 먼저 "당신 파일에는 아무 문제가 없다"고 말한다. 대기 초를 담은
    // 문장은 숫자가 매번 달라 사전 키가 될 수 없고, 서버의 원문(limits.py::_slow_down)
    // 과 같은 이유로 영어로 남는다 — 이 화면의 다른 숫자 문장들과 같은 취급이다.
    "Nothing is wrong with your file": "당신 파일에는 아무 문제가 없습니다",
    "This is a pause, not a refusal. This copy did not take the document just now, so it was never opened and nothing you have done in this session changed. The same file works when you try again.":
      "이것은 거절이 아니라 잠깐 멈춤입니다. 이 서버가 방금은 그 문서를 받지 않았고, 그래서 문서를 열어 보지도 않았으며, 이번 세션에서 하신 일도 그대로 남아 있습니다. 같은 파일로 다시 하시면 됩니다.",
    "You can try again now.": "이제 다시 하실 수 있습니다.",
    "Nothing is wrong with your file. This copy paused, and the same document can be read again in a moment.":
      "당신 파일에는 아무 문제가 없습니다. 이 서버가 잠깐 멈췄을 뿐이고, 같은 문서를 곧 다시 읽을 수 있습니다.",

    "Kind of document": "문서 종류",
    "How we read it": "어떻게 읽었는지",
    "Fields we could read": "읽어낸 항목",
    "read as a picture, because the file had no text in it (OCR)":
      "파일에 글자가 없어서 그림으로 읽었습니다 (OCR)",
    "read from the text in the file": "파일 안의 글자에서 읽었습니다",
    "no date we could read on this document": "이 문서에서 읽어낼 수 있는 날짜가 없습니다",
    "Values read from the document you uploaded.": "올리신 문서에서 읽어낸 값입니다.",

    // ⚠ 읽지 못했을 때의 안내. 이것은 오류가 아니라 정상 동작이다. 원문이 스스로
    //   "That is an answer, not a failure" 라고 말한다. 한국어가 "실패했습니다" 로
    //   읽히면 이 화면의 논지가 뒤집히므로, 첫 문장을 그 선언으로 시작한다.
    "We could not confidently read any field on this document":
      "이 문서에서 확신을 가지고 읽어낸 항목이 하나도 없습니다",
    "That is an answer, not a failure. We only report a value when we can point at the place on the page it came from, so when we cannot find it we say nothing rather than guess. Nothing here has gone wrong and nothing has been recorded against you.":
      "이것은 실패가 아니라 하나의 답입니다. 저희는 값이 나온 문서상의 자리를 가리킬 수 있을 때만 그 값을 알려 드립니다. 그래서 찾지 못하면 짐작하는 대신 아무 말도 하지 않습니다. 잘못된 일은 일어나지 않았고, 당신에게 불리하게 기록된 것도 없습니다.",
    "Documents we cannot read usually look like one of these:":
      "읽지 못하는 문서는 대개 다음 중 하나입니다:",
    "The labels are worded differently from the ones we know — \"TOTAL EARNINGS\" where we look for \"GROSS PAY\".":
      "항목 이름이 저희가 아는 것과 다르게 적혀 있습니다 — \"GROSS PAY\" 를 찾는 자리에 \"TOTAL EARNINGS\" 가 있는 경우.",
    "The values sit beside their labels, or in a table, rather than underneath them.":
      "값이 항목 이름 아래가 아니라 옆에 있거나 표 안에 있습니다.",
    "It is a form we have never seen, or the kind of document chosen above is not the kind of document this is.":
      "저희가 본 적 없는 양식이거나, 위에서 고르신 문서 종류가 이 문서의 종류와 다릅니다.",
    "It is a scan that is too faint or too skewed to read.":
      "스캔이 너무 흐리거나 많이 기울어져 읽을 수 없습니다.",
    "You can try choosing a different kind of document above, or hand this one to a person to read. A housing professional reading it is a normal outcome, not a fallback.":
      "위에서 다른 문서 종류를 골라 다시 해 보시거나, 이 문서를 사람에게 넘겨 읽게 하셔도 됩니다. 공인 주택 전문가가 읽는 것은 차선책이 아니라 정상적인 결말입니다.",
    "We could not confidently read any field from that document.":
      "그 문서에서 확신을 가지고 읽어낸 항목이 하나도 없습니다.",

    "What this reading does not tell you": "이 판독이 말해 주지 않는 것",

    // ── api/upload.py — 판독의 한계와 거절 사유 ────────────────────────────────
    "We read each value from the label above it. We do not check the values against each other, so a document whose own arithmetic disagrees still reads cleanly here.":
      "각 값은 그 위에 있는 항목 이름을 보고 읽습니다. 값들끼리 서로 대조하지는 않습니다. 그래서 문서 안의 계산이 서로 맞지 않아도 여기서는 깨끗하게 읽힙니다.",
    "This document was read on its own. It is never added to any example household and it changes no figure in any of them.":
      "이 문서는 그 문서 하나만 놓고 읽었습니다. 어떤 예시 세대에도 절대 합쳐지지 않고, 그쪽의 어떤 숫자도 바꾸지 않습니다.",
    "Everything you upload in this session is kept together as one file of your own. You can open that file from the list on step 1 and walk every step with it. Deleting the session removes all of it.":
      "이번 세션에서 올리신 문서는 전부 하나의 파일로 함께 보관됩니다. 1단계의 목록에서 그 파일을 열어 모든 단계를 걸어 볼 수 있습니다. 세션을 삭제하면 전부 사라집니다.",
    "This session already holds 6 uploaded documents, and they all stay in this session's memory. That is the ceiling. You can open the file made of the ones you have, or delete the session on step 6 and start again.":
      "이번 세션에는 이미 올린 문서가 6개 있고, 전부 이 세션의 메모리에 남아 있습니다. 거기까지가 상한입니다. 지금 있는 문서들로 이루어진 파일을 여시거나, 6단계에서 세션을 삭제하고 새로 시작하실 수 있습니다.",

    // ── app.js: 업로드 파일 — 올린 문서들이 이루는 세션 자신의 파일 ──────────
    "Walk the six steps with your own documents": "당신의 문서로 여섯 단계를 걸어 보세요",
    "Everything you upload in this session is kept together as one file. Open it and every step reads your documents — you can fix values, see the numbers, check the list, and take the packet.":
      "이번 세션에서 올리신 문서는 전부 하나의 파일로 함께 보관됩니다. 그 파일을 열면 모든 단계가 당신의 문서를 읽습니다 — 값을 고치고, 숫자를 보고, 목록을 점검하고, 서류 묶음을 받으실 수 있습니다.",
    "Documents with scanned or photographed parts can take up to a minute to read — plain documents are quick.":
      "스캔하거나 사진으로 찍은 부분이 있는 문서는 읽는 데 1분까지 걸릴 수 있습니다 — 일반 문서는 금방 읽힙니다.",

    // ── app.js + api/nominate.py: 종류 지명 — 기계가 인쇄된 제목에서 지명하고,
    //    사람이 확인한다. 근거 문장(RULES 쪽)은 필수이지 장식이 아니다. ─────────
    "Read the kind off the page (usual)": "종류를 페이지에서 읽기 (기본)",
    "Choose the kind of document yourself (optional)": "문서 종류를 직접 고르기 (선택)",
    "You usually do not have to answer: the page itself prints what it is at the top, and we read the kind from those printed words, then show you the words we used. If the page does not announce itself, we ask here instead of guessing.":
      "보통은 답하실 필요가 없습니다: 페이지가 맨 위에 스스로 무엇인지 인쇄하고 있어서, 저희는 그 인쇄된 글자에서 종류를 읽고, 어떤 글자를 근거로 삼았는지 보여 드립니다. 페이지가 스스로 밝히지 않으면 짐작하는 대신 여기서 여쭤봅니다.",
    // 지명 배너의 머리말. 뒤에 <strong>종류</strong>가 별도 노드로 이어지므로,
    // 한국어는 콜론으로 끝나는 명사구가 어순을 지킨다.
    "We read this as a": "기계가 읽은 이 문서의 종류:",
    // item 3: 페이지가 스스로를 밝히지 못했을 때 보이는 기본값 가정. 한 클릭으로 고칠 수
    // 있는 **보이는** 가정이라 화면에 이렇게 드러난다.
    "We assumed this is a": "가정한 이 문서의 종류:",
    "Not a pay stub? Change the kind": "급여명세서가 아닌가요? 종류 바꾸기",
    "If that is not what this is, change it here and we will read it again.":
      "이 문서가 그 종류가 아니라면, 여기서 종류를 바꿔 주시면 다시 읽겠습니다.",
    "You did not have to choose, and nothing is locked in.":
      "직접 고르실 필요가 없었고, 아직 확정된 것도 없습니다.",
    "Not right? Change the kind": "아닌가요? 종류 바꾸기",
    "Read it again as": "이 종류로 다시 읽기",
    "Read this document again": "이 문서 다시 읽기",
    // 결합 문서(한 파일 안 여러 문서)의 파일 요약과 값 표 캡션.
    "This file holds more than one document, so each page was read as its own kind. Here is what is where; each is shown in full below.":
      "이 파일에는 문서가 여러 개 들어 있어, 각 페이지를 저마다의 종류로 읽었습니다. 무엇이 어디에 있는지 아래에 정리했고, 각 문서는 그 아래에 전부 표시됩니다.",
    "Values read from this document.": "이 문서에서 읽어낸 값입니다.",
    "The page did not announce what kind of document it is. Choose the kind, then read it again.":
      "페이지가 어떤 종류의 문서인지 스스로 밝히지 않았습니다. 종류를 고른 뒤 다시 읽어 주세요.",
    "The file is no longer held by the page. Choose it again above.":
      "화면이 그 파일을 더 이상 들고 있지 않습니다. 위에서 다시 골라 주세요.",
    // 서버(api/upload.py::_NOT_ANNOUNCED)의 세 가지 "묻기로 함" 사유.
    "This page has no text we can read for a title — it looks like a scan — so the page does not announce what it is. Choose the kind of document below and we will read it that way.":
      "이 페이지에는 제목으로 읽을 글자가 없습니다 — 스캔본으로 보입니다 — 그래서 페이지가 스스로 무엇인지 밝히지 못합니다. 아래에서 문서 종류를 골라 주시면 그 종류로 읽겠습니다.",
    "The page did not announce what it is: nothing printed at the top of it matches a kind of document we know. Choose the kind of document below and we will read it that way.":
      "페이지가 스스로 무엇인지 밝히지 않았습니다: 맨 위에 인쇄된 어떤 글자도 저희가 아는 문서 종류와 일치하지 않습니다. 아래에서 문서 종류를 골라 주시면 그 종류로 읽겠습니다.",
    "The page prints titles for more than one kind of document, and choosing between them would be a guess. Choose the kind of document below and we will read it that way.":
      "페이지에 서로 다른 종류의 제목이 함께 인쇄되어 있어, 그중 하나를 고르는 것은 짐작이 됩니다. 아래에서 문서 종류를 골라 주시면 그 종류로 읽겠습니다.",

    // ── app.js: 단계별 읽기 표시 (실제 단계 이름; 속도는 표시用 페이싱) ────────
    "Reading the text on the page…": "페이지의 글자를 읽는 중…",
    "Read. Drawing what was found…": "읽었습니다. 찾은 값을 그리는 중…",
    "No text on the page — the text pass came back empty.":
      "페이지에 글자가 없습니다 — 텍스트 읽기가 빈손으로 돌아왔습니다.",
    "Read the text on the page. Drawing each value where it was found…":
      "페이지의 글자를 읽었습니다. 각 값을 찾은 자리에 그리는 중…",

    // ── app.js: 올린 문서 한 장 지우기 ────────────────────────────────────────
    "Remove this document": "이 문서 지우기",
    "Remove this document from the session?": "이 문서를 세션에서 지울까요?",
    "This removes only this document from your session. Your corrections and confirmations on other documents stay.":
      "이 문서 하나만 세션에서 지워집니다. 다른 문서에 하신 정정과 확인은 그대로 남습니다.",
    "Yes — remove it": "네 — 지웁니다",
    "Keep it": "그대로 둡니다",
    "The document was removed. No uploaded documents are left, so the file made of them is gone from the list.":
      "문서를 지웠습니다. 올린 문서가 하나도 남지 않아, 그 문서들로 이루어진 파일도 목록에서 사라졌습니다.",

    // ── app.js: 월 단위 날짜의 정직한 삼분법 — 다음 걸음 문장(정적) ───────────
    "Page 2 still lists this as an open item, because the day itself is not on the page. If you know the exact date, fix it on the date row below.":
      "날짜의 일(日)이 페이지에 없으므로 2페이지는 이것을 여전히 미해결 항목으로 둡니다. 정확한 날짜를 아신다면 아래 날짜 행에서 고쳐 주세요.",
    "Ask for a recent copy dated to the day. Page 2 lists this as an open item.":
      "일(日)까지 적힌 최근 사본을 요청하세요. 2페이지에 미해결 항목으로 올라 있습니다.",

    // ── app.js: HH-003/HH-006 — READY 배너 옆의 "없음" 카드가 왜 모순이 아닌지 ──
    "Why the ready banner can stand beside this card. The letter has one job here: to show where your wage comes from. The two pay stubs in your file already do that job, and they agree with each other. The challenge's own answer key marks this file ready with the letter still missing. We still list the letter as missing, because hiding a gap is worse than showing one.":
      "'검토 준비됨' 배너가 이 카드 옆에 설 수 있는 이유. 이 자리에서 재직증명서가 할 일은 하나입니다: 임금의 출처를 보여 주는 것. 제출된 급여명세서 두 장이 이미 그 일을 하고 있고, 두 장은 서로 일치합니다. 과제의 공식 정답지도 이 편지가 없는 채로 이 파일을 준비됨으로 표시합니다. 그래도 저희는 이 편지를 없음으로 계속 올려 둡니다. 빈자리를 숨기는 것이 보여 주는 것보다 나쁘기 때문입니다.",

    // ── index.html: 운영자 대시보드가 없는 이유 (심사위원용 화면) ─────────────
    "There is no operator dashboard, deliberately": "운영자 대시보드는 일부러 없습니다",
    "An operator-side “who is ready” list is a ranking by another name: the moment applicants appear as rows on one screen, their order — readiness, date, anything — becomes a queue someone reads as priority, and ranking is what the brief forbids. So this product has no such screen, and its operator-side output is exactly one thing: the packet the renter hands over, one file at a time, on the renter's own initiative. The office sees a household when, and only because, that household chose to be seen.":
      "운영자 쪽의 “누가 준비됐는가” 목록은 이름만 다른 순위표입니다: 신청자들이 한 화면에 행으로 나타나는 순간 그 순서는 — 준비 상태든 날짜든 무엇이든 — 누군가가 우선순위로 읽는 줄이 되고, 순위 매기기는 브리프가 금지한 바로 그것입니다. 그래서 이 제품에는 그런 화면이 없고, 운영자 쪽으로 나가는 산출물은 정확히 하나입니다: 세입자가 스스로, 한 번에 한 파일씩 건네는 서류 묶음. 사무소는 세대가 보이기로 선택했을 때, 오직 그 이유로만 그 세대를 봅니다.",

    // ── app.js: 빈 상태 두 갈래 (R26: 기권은 안내이지 판정이 아니다) ─────────
    "There is no document to show yet": "아직 보여드릴 문서가 없습니다",
    "This step reads whatever file is open, and none is — so there is nothing here to be right or wrong about. This is not an empty result, it is an empty desk.":
      "이 단계는 열려 있는 파일을 읽는데, 지금은 열린 파일이 없습니다 — 그래서 여기에는 맞고 틀릴 것이 아직 없습니다. 빈 결과가 아니라 빈 책상입니다.",
    "Step 1 does both of the things that change that: it reads a PDF you choose, and it opens one of the six prepared example files.":
      "그것을 바꾸는 두 가지 일을 모두 1단계가 합니다: 고르신 PDF 를 읽는 것, 그리고 준비된 예시 파일 여섯 중 하나를 여는 것입니다.",
    "Go to step 1": "1단계로 가기",
    "Your uploaded documents form a file you can open": "올리신 문서들이 하나의 파일이 되어 있습니다",
    "This step reads whatever file is open, and none is. The documents you uploaded on step 1 are kept together as a file of your own — open it and this step reads them.":
      "이 단계는 열려 있는 파일을 읽는데, 지금은 열린 파일이 없습니다. 1단계에서 올리신 문서들은 당신 자신의 파일 하나로 함께 보관되어 있습니다 — 그 파일을 열면 이 단계가 그것을 읽습니다.",

    // ── app.js: 파일 선택 패널 — 열기·닫기·처음부터 다시 ─────────────────────
    "Your uploaded documents are open. Use the list below to open a different one, or close it to start from your own document.":
      "내가 올린 문서 파일이 열려 있습니다. 다른 파일을 열려면 아래 목록을 쓰시고, 내 문서로 시작하려면 닫으세요.",
    "Close this file": "이 파일 닫기",
    "Start over": "처음부터 다시",
    "Start over?": "처음부터 다시 시작할까요?",
    "Yes, clear this session": "네, 이 세션을 비웁니다",
    "Keep working": "계속 작업하기",
    "The session could not be cleared": "세션을 비우지 못했습니다",

    // ── app.js: 행 안 편집기와 페이지 가리키기 ───────────────────────────────
    "This is wrong — fix it": "잘못 읽었어요 — 고치기",
    "Save": "저장",
    "Cancel": "취소",
    "Point at it on the page": "페이지에서 그 자리를 가리키기",
    "The box holds what we read. Type what the page really shows, then choose Save.":
      "칸에는 저희가 읽은 값이 들어 있습니다. 페이지가 실제로 보여 주는 값을 입력하고 저장을 누르세요.",
    "This is the area you pointed at, enlarged. The box holds what the machine read there — a suggestion, nothing more. If the picture says something else, type that instead.":
      "가리키신 영역을 확대한 것입니다. 칸에는 기계가 거기서 읽은 값이 들어 있습니다 — 제안일 뿐, 그 이상이 아닙니다. 그림이 다른 값을 말하고 있다면 그 값을 입력하세요.",
    "This is the area you pointed at, enlarged. We could not read it — type what it says.":
      "가리키신 영역을 확대한 것입니다. 저희는 읽지 못했습니다 — 뭐라고 쓰여 있는지 입력해 주세요.",
    "We could not read that area — type what it says.":
      "그 영역을 읽지 못했습니다 — 뭐라고 쓰여 있는지 입력해 주세요.",
    "Drag a box around the value on the page above. Press Escape to stop. Typing the value works without this.":
      "위 페이지에서 값 주위로 상자를 끌어 그려 주세요. 그만두려면 Esc 를 누르세요. 값은 이 도구 없이 직접 입력하셔도 됩니다.",
    "Nothing here means approved, denied, or ineligible. A qualified housing professional makes that determination.":
      "여기의 어떤 내용도 승인·거절·부적격을 뜻하지 않습니다. 그 판단은 공인 주택 전문가가 합니다.",
    "This page had no text layer, so it was read by OCR on page 1 only. OCR recovers fewer fields than a text layer does, and what it cannot read it declines to guess.":
      "이 페이지에는 텍스트 레이어가 없어서 1페이지만 OCR 로 읽었습니다. OCR 은 텍스트 레이어보다 적은 항목을 건져 내고, 읽지 못한 것은 짐작하지 않고 답하지 않습니다.",
    // item 4: 종류는 파일 이름에서 오지 않는다 — 페이지가 인쇄한 제목이나 사람의 선택에서만.
    "Choose what kind of document this is. The kind is never taken from the file name — it comes from the title the page prints at the top, or from your choice here. Without either, there is no kind to read it as.":
      "이 문서가 어떤 종류인지 골라 주세요. 종류는 파일 이름에서 가져오지 않습니다 — 페이지 맨 위에 인쇄된 제목이나, 여기서 하신 선택에서만 옵니다. 둘 다 없으면 어떤 종류로 읽을지 알 수 없습니다.",
    "That file is empty.": "그 파일은 비어 있습니다.",
    "That file is not a PDF. Its first bytes are not a PDF header, whatever its name or type says.":
      "그 파일은 PDF 가 아닙니다. 이름이나 형식이 무어라 하든, 첫 바이트가 PDF 헤더가 아닙니다.",

    // ── app.js — 세션 수명: 삭제와 되돌리기 ────────────────────────────────────
    // ⚠ 이 구역에서 두 가지가 반드시 남아야 한다. ① 되돌릴 수 없다는 것,
    //   ② 새로 시작해도 정정은 복구되지 않는다는 것. 둘 중 하나라도 빠지면
    //   삭제 버튼을 누르는 사람이 무엇을 잃는지 모르게 된다.
    "Delete what this service is holding": "이 서비스가 가지고 있는 것 삭제하기",
    "Everything this service holds about the household lives in one session. Deleting it removes the documents, the values read from them, and every correction from the server process. Requests that follow return 404 because there is nothing left to answer with.":
      "이 서비스가 이 세대에 대해 가지고 있는 것은 모두 세션 하나 안에 있습니다. 세션을 삭제하면 서류, 그 서류에서 읽어낸 값, 그리고 정정한 내용이 서버 프로세스에서 사라집니다. 그 뒤의 요청은 404 를 돌려받습니다. 답할 것이 남아 있지 않기 때문입니다.",
    "This cannot be undone, and it does not restore: to carry on afterwards you start again with a new session, without the corrections you made. Download your packet first if you want to keep it. The pack these documents came from is untouched either way.":
      "이 작업은 되돌릴 수 없고, 복구되지도 않습니다. 이후에 계속하시려면 새 세션으로 다시 시작해야 하며, 그때 정정하신 내용은 없습니다. 남겨 두고 싶으시면 신청 서류 묶음을 먼저 내려받으세요. 이 서류들이 나온 팩은 어느 쪽이든 그대로입니다.",
    "Delete this session now": "이 세션을 지금 삭제",
    "Start again with a new session": "새 세션으로 다시 시작",

    "You deleted this session": "이 세션을 삭제하셨습니다",
    "The documents, the values read from them, and every correction were removed from the server process, and this page is holding nothing. There is no packet to download and nothing here to show, because there is nothing left to answer with.":
      "서류, 그 서류에서 읽어낸 값, 정정한 내용이 서버 프로세스에서 사라졌고, 이 화면도 아무것도 가지고 있지 않습니다. 내려받을 신청 서류 묶음도, 여기서 보여 드릴 것도 없습니다. 답할 것이 남아 있지 않기 때문입니다.",
    "Starting again does not bring any of it back. It loads the household from the pack into a new session, and any correction you made is gone with the old one.":
      "다시 시작해도 그중 어느 것도 돌아오지 않습니다. 팩에서 세대를 새 세션으로 불러올 뿐이고, 정정하신 내용은 지운 세션과 함께 사라졌습니다.",
    "This session was deleted, so there is nothing to answer with. Starting again loads the household from the pack as a new session.":
      "이 세션은 삭제되었습니다. 답할 것이 남아 있지 않습니다. 다시 시작하면 팩에서 세대를 새 세션으로 불러옵니다.",
    "You deleted this session, so there is nothing here to be unsure about.":
      "이 세션을 삭제하셨으므로, 여기에 확신하지 못할 것이 없습니다.",

    "There is nothing left to delete": "삭제할 것이 남아 있지 않습니다",
    "This session was already deleted. Nothing was sent to the server this time, because there is no longer an id to send.":
      "이 세션은 이미 삭제되었습니다. 이번에는 서버로 아무것도 보내지 않았습니다. 보낼 id 가 더 이상 없기 때문입니다.",
    "This session was already deleted.": "이 세션은 이미 삭제되었습니다.",
    "Session data cleared from this page": "이 화면이 가지고 있던 세션 데이터를 비웠습니다",
    "Offline there is no server session to destroy, so this clears everything the page was holding: the report, the correction, and the selected document.":
      "오프라인에서는 없앨 서버 세션이 없으므로, 이 화면이 가지고 있던 것을 비웁니다. 보고서, 정정 내용, 그리고 고른 문서입니다.",
    "With the API connected, this same button deletes the session inside the server process.":
      "API 가 연결되어 있으면, 같은 버튼이 서버 프로세스 안의 세션을 삭제합니다.",
    "Deleted, and checked": "삭제했고, 확인했습니다",
    "Deleted, but the check did not come back as expected": "삭제했지만, 확인 결과가 예상과 달랐습니다",
    "The follow-up request could not be made.": "뒤이은 확인 요청을 보내지 못했습니다.",
    "Session deleted. The follow-up request returned 404. There is nothing left on this page.":
      "세션을 삭제했습니다. 뒤이은 요청은 404 를 돌려받았습니다. 이 화면에 남은 것이 없습니다.",
    "Session deleted, but the follow-up request did not return 404.":
      "세션을 삭제했지만, 뒤이은 요청이 404 를 돌려받지 않았습니다.",

    "The correction could not be undone": "정정을 되돌리지 못했습니다",
    "The correction could not be undone. The report still shows the corrected value.":
      "정정을 되돌리지 못했습니다. 보고서에는 여전히 정정된 값이 보입니다.",
    "The household could not be loaded again": "세대를 다시 불러오지 못했습니다",

    // ── app.js — 규칙 id 가 근거로 연결된 자리 ─────────────────────────────────
    // 링크 글자 자체는 아래 RULES 가 만든다(출처 위치 + 호스트 조합이라서).
    // 여기 있는 것은 그 목록의 머리말이다.
    "Rules this response stands on:": "이 응답이 근거로 삼은 규칙:",
    "rules: ": "규칙: ",
    "LIHTC property data description": "LIHTC 물건 데이터 설명",
    "Layer description and LVL2KX codes": "레이어 설명과 LVL2KX 코드",

    // ── app.js — 우리 성적표: 읽기 쉬움 측정 ───────────────────────────────────
    "flesch kincaid grade": "플레시-킨케이드 학년",
    "smog grade": "SMOG 학년",
    "spread between the two": "두 값의 차이",
    "smog is extrapolated": "SMOG 는 외삽값",
    "screens too short to measure": "측정하기에 너무 짧은 화면",
    "minimum sample words": "표본 최소 단어 수",
    "widest spread": "가장 큰 차이",
    "anchors missing": "근거가 없는 항목",
    "anchors for unknown intents": "모르는 의도에 붙은 근거",
    "anchors not round tripping": "왕복이 되지 않는 근거",
    "none found": "없음",
    "screens": "화면",
    "intents": "의도",
    "status": "상태",
    "measured": "측정함",
    // 표 캡션은 두 문장이 한 텍스트 노드로 붙어 나온다. 조각으로는 잡히지 않으므로
    // 붙은 모양 그대로 키를 둔다.
    "Values read from the document you uploaded. Choose a field name to highlight its box on the page.":
      "올리신 문서에서 읽어낸 값입니다. 항목 이름을 고르면 문서 위의 근거 위치가 강조됩니다.",
    "Choose a field name to highlight its box on the page.":
      "항목 이름을 고르면 문서 위의 근거 위치가 강조됩니다.",
    "No file chosen": "고른 파일 없음",
    "Two formulas, reported together with the gap between them. A per-string grade is not defensible and is not produced. SMOG needs 30 sentences to be used as defined; screens below that are marked as extrapolated. WCAG 2.2 SC 3.1.5 Reading Level is Level AAA and is not required at AA -- we adopt it voluntarily and do not claim AA obliges it.":
      "공식 두 개를, 둘 사이의 차이와 함께 보고합니다. 문장 하나하나에 등급을 매기는 것은 근거를 댈 수 없어 내지 않습니다. SMOG 는 정의대로 쓰려면 문장 30 개가 필요하므로, 그보다 짧은 화면은 외삽값으로 표시합니다. WCAG 2.2 SC 3.1.5 읽기 수준은 AAA 등급이고 AA 에서는 요구되지 않습니다 — 저희가 자발적으로 채택한 것이며, AA 가 이를 의무로 삼는다고 주장하지 않습니다.",

    /* ── 2페이지 재구성 (6단계 → 2페이지) ──────────────────────────────────────
     * 세입자 흐름이 여섯 단계 화면에서 두 페이지로 합쳐졌다. 옛 키는 지우지 않는다 —
     * 키가 안 맞으면 영어로 남는 구조라 해가 없고, 지우면 되돌리기 어렵다. 아래는
     * 새 화면 구조가 만든 문장들이다. */

    // 페이지 캡션·레일·이동
    "Page 1 of 2": "2페이지 중 1페이지",
    "Page 2 of 2": "2페이지 중 2페이지",
    "Ready to hand over": "건네줄 준비",
    "Pages": "페이지",
    "Continue to page 2: what it adds up to, and your packet":
      "2페이지로 계속: 합산 결과와 신청 서류 묶음",
    "Back to page 1: your documents": "1페이지로 돌아가기: 내 서류",
    "Change on page 1": "1페이지에서 바꾸기",
    "Go to page 1": "1페이지로 가기",
    "No document has been read yet, so this page has nothing of yours to show.":
      "아직 읽은 문서가 없어서, 이 페이지에 보여 드릴 당신의 것이 없습니다.",
    "— the file made of your uploads.": "— 올리신 문서로 만든 파일입니다.",

    // 1페이지 도입문과 예시 안내
    "RealDoor reads a document you give it. It shows you where on the page every value came from; choose a field name to light up its box. If a value is wrong, fix it on its row — the numbers that depend on it are worked out again, in place.":
      "RealDoor 는 당신이 준 문서를 읽습니다. 각 값이 문서의 어느 위치에서 나왔는지 보여 드리고, 항목 이름을 고르면 그 상자가 켜집니다. 값이 틀렸으면 그 행에서 바로 고치세요 — 그 값에 기대는 숫자들이 그 자리에서 다시 계산됩니다.",
    "If you would rather look around first, this copy carries six made-up household files. They belong to nobody. Everything both pages do — the evidence boxes, the corrections, the checklist, the packet — works the same on them as on a document of your own.":
      "먼저 둘러보고 싶으시면, 이 사본에는 지어낸 세대 파일 여섯 개가 들어 있습니다. 누구의 것도 아닙니다. 두 페이지가 하는 모든 것 — 근거 상자, 정정, 점검 목록, 서류 묶음 — 은 당신의 문서에서와 똑같이 그것들에서도 작동합니다.",
    "See each value we read and the box it came from. Confirm it, or fix it on its row and watch the numbers move in place.":
      "읽어낸 각 값과 그 값이 나온 상자를 봅니다. 확인하거나, 그 행에서 바로 고치고 숫자가 그 자리에서 움직이는 것을 봅니다.",
    "The yearly figure and the frozen limit it is compared against, the checklist of what is still open, then the packet you hand to the housing office.":
      "연 소득 금액과 그 비교 대상인 동결된 상한, 아직 남은 것의 점검 목록, 그리고 주택 사무소에 건네실 서류 묶음입니다.",

    // 2페이지 제목·도입문·구획
    "See what your file adds up to, then take your packet":
      "파일이 얼마로 합산되는지 보고, 신청 서류 묶음을 받으세요",
    "Three things, in order. First, the yearly figure we worked out, and the frozen limit it is compared against. Then the checklist: what is present, what is missing, what is out of date. Last, the packet you hand to the housing office. A comparison is not a determination.":
      "세 가지가 순서대로 있습니다. 먼저, 저희가 계산한 연 소득 금액과 그 비교 대상인 동결된 상한입니다. 다음은 점검 목록입니다: 무엇이 있고, 무엇이 없고, 무엇의 기한이 지났는지요. 마지막은 주택 사무소에 건네실 서류 묶음입니다. 비교는 판정이 아닙니다.",
    "How your yearly figure was worked out": "연 소득 금액이 어떻게 산출되었는지",
    "On this page": "이 페이지 안에서",
    "a year.": "— 한 해로 합산한 금액입니다.",
    "no threshold applies": "적용되는 기준액 없음",
    "Show the full working — every input, formula and rule":
      "전체 계산 과정 펼치기 — 모든 입력값·계산식·규칙",
    "The same household, in another HUD region": "같은 세대를 다른 HUD 지역에서 보면",
    "Check each answer, row by row": "답을 한 줄씩 확인하기",
    "What is inside, and who it is for": "안에 무엇이 들어 있고, 누구를 위한 것인지",
    "Check the rows below before you download, and change anything that is wrong.":
      "내려받기 전에 아래 줄들을 확인하시고, 틀린 것은 바꾸세요.",
    "Nothing is missing. Every required item is present and current.":
      "빠진 것이 없습니다. 필요한 항목이 전부 있고, 전부 유효합니다.",

    // 오류 요약과 남은 항목 (단계 → 페이지)
    "There is one open item on this page": "이 페이지에 남은 항목이 하나 있습니다",
    "One thing here needs a person to look at it": "여기, 사람이 봐야 할 것이 하나 있습니다",
    "“One thing here needs a person to look at it”": "“여기, 사람이 봐야 할 것이 하나 있습니다”",

    // 행 안에서의 정정과 그 하류 요약 (옛 2단계의 몫)
    "Your correction was used — here is what moved": "정정이 쓰였습니다 — 무엇이 움직였는지 보여 드립니다",
    "The corrected value flowed into the calculation. Nothing was hidden and no eligibility outcome follows from it. Page 2 shows the full working.":
      "정정한 값이 계산에 반영되었습니다. 숨긴 것은 없으며, 여기서 자격에 대한 어떤 결론도 따라 나오지 않습니다. 전체 계산 과정은 2페이지에 있습니다.",
    "below the documents, in the system's own words.": "(서류 아래)에 시스템 자신의 말로 적혀 있습니다.",
    "Close this summary": "이 요약 닫기",
    "Corrections this copy can replay": "이 사본이 재생할 수 있는 정정",
    "Without a server, the app can only replay corrections the pipeline actually ran. Both of these are real pipeline output: press one and the before-and-after summary appears under the row it names. Point the app at the API to edit any field.":
      "서버가 없으면 이 앱은 파이프라인이 실제로 실행한 정정만 재생할 수 있습니다. 아래 둘 다 실제 파이프라인 출력입니다: 하나를 누르면 그 정정이 가리키는 행 아래에 전·후 요약이 나타납니다. 아무 항목이나 고치려면 앱을 API 에 연결하세요.",
    "If you know the exact date, fix it on the date row below. Or ask for a copy that shows the full date. Page 2 lists this as an open item.":
      "정확한 날짜를 아시면 아래 날짜 행에서 바로 고쳐 주세요. 아니면 날짜가 다 적힌 사본을 요청하세요. 2페이지에 남은 항목으로 올라 있습니다.",
    "Work through the open items in the checklist below. Each one says what to send.":
      "아래 점검 목록의 남은 항목을 하나씩 처리해 주세요. 무엇을 보내면 되는지 각 항목에 적혀 있습니다.",

    // 질문 상자와 기록된 질문 (옛 3단계의 몫)
    "You can ask from either page, in your own words. The answer opens below, with the rule id, the authority behind it and the date it took effect. The recorded questions this copy can always answer are in the list underneath.":
      "어느 페이지에서든 자기 말로 물어보실 수 있습니다. 답변은 아래에 열리며, 규칙 id, 그 근거가 되는 기관, 시행일이 함께 붙습니다. 이 사본이 언제나 답할 수 있는 기록된 질문은 그 아래 목록에 있습니다.",
    "Questions this copy has an answer on record for. Press one and the answer opens below, in the same place a typed question's answer does.":
      "이 사본에 답이 기록되어 있는 질문들입니다. 하나를 누르면 답변이 아래에, 직접 입력한 질문의 답변과 같은 자리에 열립니다.",
    "The rest name nobody — what a rule says, and what this service does when a document tries to give it an instruction — and those are answered the same way whoever is asking. They are worth pressing with an empty desk.":
      "나머지는 누구도 지목하지 않습니다 — 규칙이 무엇이라 말하는지, 그리고 문서가 소프트웨어에 명령을 심으려 할 때 이 서비스가 어떻게 하는지 — 그래서 누가 묻든 같은 답이 나옵니다. 빈 책상으로도 눌러 볼 가치가 있습니다.",
    "Page 1 opens a prepared example in one press, or reads a document of your own.":
      "1페이지에서 준비된 예시를 한 번에 열거나, 직접 가져온 문서를 읽을 수 있습니다.",
    "questions about the rules. The recorded questions under the ask box list examples — what the frozen income limit is, how a year of income is added up, or what is still missing or out of date.":
      "규칙에 관한 질문입니다. 질문 상자 아래의 기록된 질문에 예가 있습니다 — 동결된 소득 상한이 얼마인지, 1년치 소득을 어떻게 합산하는지, 또는 아직 없거나 기한이 지난 것이 무엇인지입니다.",
    "If that is not what you meant, ask again in different words, or use a recorded question from the list under the ask box.":
      "뜻하신 바가 아니라면 다른 표현으로 다시 물어보시거나, 질문 상자 아래 목록의 기록된 질문을 쓰세요.",
    "Without a server, the questions this build did record can still be asked from the Recorded questions list under the box, and their answers open here.":
      "서버가 없어도, 이 빌드가 기록해 둔 질문들은 상자 아래 '기록된 질문' 목록에서 그대로 물어볼 수 있고, 그 답변은 여기에 열립니다.",
    "no file is open, so there was nothing to answer from. Page 1 reads a document you upload, or opens a prepared example file. Then ask again.":
      "열려 있는 파일이 없어서, 답할 근거가 없었습니다. 1페이지에서 직접 올린 문서를 읽거나 준비된 예시 파일을 열 수 있습니다. 그런 다음 다시 물어보세요.",
    "Then open http://127.0.0.1:8077 and ask again from the box at the foot of the page.":
      "그런 다음 http://127.0.0.1:8077 을 열고, 페이지 아래의 질문 상자에서 다시 물어보세요.",
    "Then open http://127.0.0.1:8077 and return to page 1.":
      "그런 다음 http://127.0.0.1:8077 을 열고 1페이지로 돌아오세요.",

    // 빈 책상 안내 (2페이지 공용)
    "This page reads whatever file is open, and none is — so there is nothing here to be right or wrong about. This is not an empty result, it is an empty desk.":
      "이 페이지는 열려 있는 파일을 읽는데, 지금은 아무것도 열려 있지 않습니다 — 그래서 여기에는 맞고 틀릴 것이 없습니다. 이것은 빈 결과가 아니라 빈 책상입니다.",
    "Page 1 does both of the things that change that: it reads a PDF you choose, and it opens one of the six prepared example files.":
      "그것을 바꾸는 두 가지가 모두 1페이지에 있습니다: 직접 고른 PDF 를 읽는 것과, 준비된 예시 파일 여섯 개 중 하나를 여는 것입니다.",
    "This page reads whatever file is open, and none is. The documents you uploaded on page 1 are kept together as a file of your own — open it and this page reads them.":
      "이 페이지는 열려 있는 파일을 읽는데, 지금은 아무것도 열려 있지 않습니다. 1페이지에서 올리신 문서들은 하나의 파일로 함께 보관되어 있습니다 — 그 파일을 열면 이 페이지가 그것을 읽습니다.",

    // 올리기 패널 (단계 → 페이지)
    "Walk both pages with your own documents": "당신의 문서로 두 페이지를 걸어 보세요",
    "Everything you upload in this session is kept together as one file. Open it and both pages read your documents — you can fix values, see the numbers, check the list, and take the packet.":
      "이번 세션에서 올리신 것은 전부 하나의 파일로 함께 보관됩니다. 그 파일을 열면 두 페이지가 당신의 문서를 읽습니다 — 값을 고치고, 숫자를 보고, 목록을 점검하고, 서류 묶음을 받을 수 있습니다.",
    "Everything you upload in this session is kept together as one file of your own. You can open that file from the list on page 1 and walk both pages with it. Deleting the session removes all of it.":
      "이번 세션에서 올리신 문서는 전부 하나의 파일로 함께 보관됩니다. 1페이지의 목록에서 그 파일을 열어 두 페이지를 걸어 볼 수 있습니다. 세션을 삭제하면 전부 사라집니다.",
    "This session already holds 6 uploaded documents, and they all stay in this session's memory. That is the ceiling. You can open the file made of the ones you have, or delete the session at the end of page 2 and start again.":
      "이 세션에는 이미 올리신 문서 6장이 있고, 전부 이 세션의 메모리에 있습니다. 그것이 상한입니다. 지금 있는 것으로 만들어진 파일을 열거나, 2페이지 끝에서 세션을 삭제하고 다시 시작하실 수 있습니다.",

    // 판정 화면(심사위원용)의 새 안내문
    "Not part of the renter's walkthrough": "세입자의 진행 과정에는 포함되지 않는 화면",
    "This walkthrough takes about ten minutes. The prepared example files are already loaded, so you can go straight through it without uploading anything. Page 1 also lets you read a synthetic document of your own, held in memory for this session only. Nothing is sent anywhere. You can stop at any point and your work stays on this device.":
      "이 과정은 약 10분 걸립니다. 준비된 예시 파일은 이미 불러와 있어서, 아무것도 올리지 않고 그대로 끝까지 진행하실 수 있습니다. 1페이지에서는 직접 만드신 합성 문서를 올려 읽어 볼 수도 있습니다. 그 문서는 이번 세션의 메모리에만 있습니다. 어디로도 전송되지 않습니다. 어느 지점에서든 멈출 수 있고 작업 내용은 이 기기에 남습니다.",
    "The renter's walkthrough is two pages, in the order they are presented. It opens on page 1, so this list is a description of it rather than a gate in front of it. It used to be six ordered step-screens; the owner's call was that six screens were too big an obstacle, so the same work now lives on two pages and nothing was dropped.":
      "세입자의 진행 과정은 두 페이지이며, 제시되는 순서대로 적었습니다. 1페이지에서 바로 시작하므로, 이 목록은 앞을 막는 관문이 아니라 설명입니다. 원래는 여섯 단계 화면이었는데, 여섯 화면은 너무 큰 장애물이라는 오너의 결정에 따라 같은 일이 이제 두 페이지에 있으며, 빠진 것은 없습니다.",
    "The challenge brief specifies a six-step acceptance demo. Our walkthrough is two pages written for the renter, not for that list, so the two do not line up one to one. This is the mapping, and every acceptance step remains individually demonstrable.":
      "과제 설명서는 6단계 수용 데모를 요구합니다. 우리의 진행 과정은 그 목록이 아니라 세입자를 위해 쓴 두 페이지라서, 둘은 1대1로 맞아떨어지지 않습니다. 아래가 그 대응표이며, 각 수용 단계는 여전히 하나씩 따로 시연할 수 있습니다.",
    "— page 1. The upload panel is the front door, and one press opens a prepared example instead; either way every value carries the box on the page it came from. An uploaded document is read on its own; the session's uploads together form a file of their own that both pages can walk.":
      "— 1페이지. 올리기 패널이 정문이고, 한 번의 누름으로 준비된 예시를 대신 열 수도 있습니다. 어느 쪽이든 모든 값은 그것이 나온 문서상의 근거 위치를 달고 있습니다. 올리신 문서는 그 문서 하나만 놓고 읽으며, 세션의 업로드들은 함께 자기 파일을 이루어 두 페이지를 걸을 수 있습니다.",
    "— page 1. “This is wrong — fix it” opens an editor on the row itself; when the correction commits, the before/after summary — the recomputed figure, the threshold move, or the recorded-but-not-used explanation — appears in place under that document's table.":
      "— 1페이지. “잘못 읽었어요 — 고치기”가 행 자체에 편집기를 엽니다. 정정이 반영되면 전·후 요약 — 다시 계산된 금액, 기준액의 이동, 또는 기록만 되고 쓰이지 않은 이유 — 이 그 문서의 표 아래, 바로 그 자리에 나타납니다.",
    "— the ask box pinned at the foot of every page. Its answers carry the rule id, authority, effective date and source; the recorded questions, including the eligibility refusal, are in the “Recorded questions” list under the same box.":
      "— 모든 페이지 아래에 고정된 질문 상자입니다. 그 답변에는 규칙 id, 근거 기관, 시행일, 출처가 붙습니다. 자격 거부 시연을 포함한 기록된 질문은 같은 상자 아래 “기록된 질문” 목록에 있습니다.",
    "— page 2, “How your yearly figure was worked out”.":
      "— 2페이지, “연 소득 금액이 어떻게 산출되었는지”.",
    "— page 2, “What is missing or out of date” and then “Check what we found, then take your packet”, top to bottom on the same page.":
      "— 2페이지, “무엇이 없거나 기한이 지났는지”에 이어 “찾아낸 내용을 확인하고, 신청 서류 묶음을 받으세요”가 같은 페이지에 위에서 아래로 이어집니다.",
    "It is not part of the walkthrough because it is not a task the renter performs. Both the adversarial suite and the static no-decision guard exercise these paths on every run.":
      "세입자가 수행하는 일이 아니기 때문에 진행 과정에 넣지 않았습니다. 적대적 시험 묶음과 정적 무판정 가드가 매 실행마다 이 경로들을 통과시킵니다."
  };

  // ── 평문 계층(api/plain.py)의 조립 부품 ────────────────────────────────────
  //
  // plain.py 는 문장을 템플릿에 데이터를 끼워 만든다. 날짜·금액·문서 이름이 문장
  // 한가운데 박히므로 사전의 정확 매칭으로는 한 문장도 잡히지 않는다. 그래서 각
  // 렌더러의 템플릿과 같은 모양의 정규식을 아래 RULES 에 두고, 변하는 부분만
  // 여기 함수들로 옮긴다. 데이터 자체(금액·문서 id·세대 id)는 옮기지 않는다.

  var MONTH_NUMBER = {
    January: 1, February: 2, March: 3, April: 4, May: 5, June: 6,
    July: 7, August: 8, September: 9, October: 10, November: 11, December: 12
  };

  /** "10 July 2026" → "2026년 7월 10일", "June 2026" → "2026년 6월".
   *
   *  plain.py::_pretty_date 의 두 출력 모양을 그대로 되받는다. 알아보지 못하면
   *  원문을 그대로 돌려준다 — 날짜는 데이터이고, 못 읽었다고 지어내면 안 된다. */
  function koDate(text) {
    var s = normalize(text);
    var day = s.match(/^(\d{1,2}) ([A-Z][a-z]+) (\d{4})$/);
    if (day && MONTH_NUMBER[day[2]]) {
      return day[3] + "년 " + MONTH_NUMBER[day[2]] + "월 " + Number(day[1]) + "일";
    }
    var month = s.match(/^([A-Z][a-z]+) (\d{4})$/);
    if (month && MONTH_NUMBER[month[1]]) return month[2] + "년 " + MONTH_NUMBER[month[1]] + "월";
    return s;
  }

  // plain.py::DOC_NAMES. 세입자가 부르는 이름이지 스키마 타입이 아니다. 위쪽 사전의
  // "application summary"(신청 요약서)와 여기의 "application form"(신청서)이 다른
  // 것은 영어가 다르기 때문이다 — 평문 계층은 일부러 더 쉬운 이름을 쓴다.
  var DOC_NAME_KO = {
    "application form": "신청서",
    "pay stub": "급여명세서",
    "employer's letter": "재직증명서",
    "benefit award letter": "수급 결정 통지서",
    "gig earnings statement": "긱 수입 명세서",
    "independent proof of gig earnings": "긱 수입을 뒷받침하는 독립 자료",
    "document": "서류"
  };

  function koDoc(name) {
    var key = normalize(name);
    return Object.prototype.hasOwnProperty.call(DOC_NAME_KO, key) ? DOC_NAME_KO[key] : null;
  }

  // plain.py::Context.describe 와 각 렌더러의 fallback 문구.
  var DOC_PHRASE_KO = {
    "the document": "그 서류",
    "this document": "이 서류",
    "this pay stub": "이 급여명세서",
    "your pay stub": "급여명세서",
    "your documents": "제출하신 서류",
    "your pay documents": "제출하신 급여 서류",
    "one of your documents": "제출하신 서류 중 하나"
  };

  /** "the pay stub dated 30 June 2026" → "2026년 6월 30일자 급여명세서".
   *
   *  모르는 표현이면 null 을 돌린다. 부르는 쪽은 그때 문장 전체의 번역을 포기한다.
   *  반쪽만 한국어인 문장보다 영어 한 문장이 낫다. */
  function koWhere(phrase) {
    var s = normalize(phrase);
    if (Object.prototype.hasOwnProperty.call(DOC_PHRASE_KO, s)) return DOC_PHRASE_KO[s];
    var dated = s.match(/^the (.+) dated (.+)$/);
    if (dated && koDoc(dated[1])) return koDate(dated[2]) + "자 " + koDoc(dated[1]);
    var bare = s.match(/^the (.+)$/);
    if (bare && koDoc(bare[1])) return koDoc(bare[1]);
    return null;
  }

  // plain.py::CURRENCY_SENTENCE. 날짜와 일수는 logic/constants.py 에서 오므로,
  // 문장에 박힌 값을 읽어서 다시 짓는다. 상수가 바뀌어도 따라간다.
  var CURRENCY_EN = /^A paper counts as recent only if it is dated (.+?) or later\. That is the (\d+)-day rule this project follows, counting back from (.+?)\.$/;

  function koCurrency(text) {
    var m = normalize(text).match(CURRENCY_EN);
    if (!m) return null;
    return "서류는 " + koDate(m[1]) + " 이후 날짜여야 최근 것으로 인정됩니다. 이 프로젝트가 따르는 " +
           m[2] + "일 기준이며, " + koDate(m[3]) + "부터 거꾸로 셉니다.";
  }

  // ── 규칙: 숫자나 식별자가 끼어들어 사전으로는 못 잡는 문장 ──────────────────
  // 각 항목은 [정규식, 한국어를 만드는 함수]. 함수는 잡힌 그룹을 받는다. 데이터
  // (금액·날짜·세대 id·항목 이름)는 절대 번역하지 않고 그대로 끼워 넣는다.
  var RULES = [
    // ══ api/plain.py: 데이터가 박힌 본문 ═══════════════════════════════════════
    // 각 규칙은 plain.py 의 렌더러 하나와 짝이다. 한 렌더러가 가지치기로 여러 문장을
    // 만들면 여기도 그만큼 규칙이 있다. 문서 이름이나 표현을 알아보지 못하면 null 을
    // 돌려 그 문장은 영어로 남긴다 — 절반만 한국어인 문장을 만들지 않기 위해서다.

    // _r_item_present: 갖춰져 있고 기한도 남은 항목
    [/^We have your (.+)$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null : name + "를 확인했습니다";
    }],
    [/^It is in your file and it is recent enough to use\.(?: It is dated (.+?)\.)? (A paper counts.+)$/,
      function (m) {
        var currency = koCurrency(m[2]);
        if (currency === null) return null;
        return "제출하신 서류 안에 있고, 쓸 수 있을 만큼 최근 것입니다. " +
               (m[1] ? "날짜는 " + koDate(m[1]) + "입니다. " : "") + currency;
      }],

    // _r_required_missing: 아직 없는 서류
    [/^We still need your (.+)$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null : name + "가 아직 필요합니다";
    }],
    [/^Your file does not have an? (.+) in it yet\. A housing worker needs it before they can start reading your file\.$/,
      function (m) {
        var name = koDoc(m[1]);
        return name === null ? null
          : "제출하신 서류에 아직 " + name + "가 없습니다. 주택 담당자가 검토를 시작하려면 이 서류가 있어야 합니다.";
      }],
    [/^Upload your (.+)\.$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null : name + "를 올려 주세요.";
    }],

    // _r_not_current: 기한이 지난 서류
    [/^Your (.+) is too old to use$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null : name + "가 너무 오래되어 쓸 수 없습니다";
    }],
    [/^(?:It is dated (.+?)\. )?(A paper counts.+?\.) Nothing is wrong with the rest of your file\. One out-of-date paper is enough to hold the whole file until someone replaces it\.$/,
      function (m) {
        var currency = koCurrency(m[2]);
        if (currency === null) return null;
        return (m[1] ? "날짜는 " + koDate(m[1]) + "입니다. " : "") + currency +
               " 나머지 서류에는 문제가 없습니다. 기한이 지난 서류가 하나만 있어도, " +
               "새 서류로 바뀔 때까지 전체 검토가 멈춥니다.";
      }],
    [/^Ask your employer for a new letter dated (.+) or later, then upload it\.$/, function (m) {
      return "고용주에게 " + koDate(m[1]) + " 이후 날짜의 새 증명서를 받아 올려 주세요.";
    }],
    [/^Upload your (.+), dated (.+) or later\.$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null
        : koDate(m[2]) + " 이후 날짜의 " + name + "를 올려 주세요.";
    }],
    [/^Ask whoever issued your paper for a new copy dated (.+) or later, then upload it\.$/, function (m) {
      return "서류를 발급한 곳에 " + koDate(m[1]) + " 이후 날짜의 새 사본을 요청해 받아 올려 주세요.";
    }],
    // expired_evidence_flagged 의 본문은 통화 문장으로 시작한다.
    [/^(A paper counts.+?\.) One paper past that line is enough to hold your file, however good the rest of it is\. That is a statement about the paper and not about you\. A fresh copy clears it and nothing else has to change\.$/,
      function (m) {
        var currency = koCurrency(m[1]);
        if (currency === null) return null;
        return currency + " 그 기준선을 넘은 서류가 하나만 있어도, 나머지가 아무리 잘 갖춰져 있어도 " +
               "검토가 멈춥니다. 이것은 서류에 대한 이야기이지 당신에 대한 이야기가 아닙니다. " +
               "새 사본 하나면 풀리고, 다른 것은 바꿀 필요가 없습니다.";
      }],

    // _r_undatable: 날짜를 알 수 없는 서류
    [/^Your (.+) does not show a full date$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null : name + "에 날짜가 다 적혀 있지 않습니다";
    }],
    [/^(?:It shows (.+?), but not which day of the month\. |It does not show which day of the month it covers\. )We need the day to work out whether the paper is recent enough\. (A paper counts.+?\.) We will not guess a day, because a guessed date could put your paper on the wrong side of that line\.$/,
      function (m) {
        var currency = koCurrency(m[2]);
        if (currency === null) return null;
        return (m[1] ? koDate(m[1]) + "까지만 적혀 있고, 며칠인지는 적혀 있지 않습니다. "
                     : "며칠자인지가 적혀 있지 않습니다. ") +
               "서류가 충분히 최근 것인지 따지려면 날짜가 필요합니다. " + currency +
               " 날짜를 지어내지는 않습니다. 지어낸 날짜 때문에 서류가 기준선의 반대편에 놓일 수 있기 때문입니다.";
      }],
    [/^Ask for a (.+) that shows the full date, or tell us the exact date on the one you already sent\.$/,
      function (m) {
        var name = koDoc(m[1]);
        return name === null ? null
          : "날짜가 다 적힌 " + name + "를 새로 요청하시거나, 이미 보내신 서류의 정확한 날짜를 알려 주세요.";
      }],

    // _r_unreadable: 읽지 못한 서류
    [/^We could not read your (.+)$/, function (m) {
      var name = koDoc(m[1]);
      return name === null ? null : name + "를 읽지 못했습니다";
    }],
    [/^Nothing on this (.+) came through clearly enough for us to use\. That is a problem with the file we received, not with you or with your paperwork\. We did not guess at what it says\.$/,
      function (m) {
        var name = koDoc(m[1]);
        return name === null ? null
          : "이 " + name + "에서 쓸 수 있을 만큼 또렷하게 읽힌 내용이 없습니다. 받은 파일의 문제이지, " +
            "당신이나 당신의 서류 문제가 아닙니다. 무엇이 적혀 있는지 짐작하지 않았습니다.";
      }],
    [/^Send the (.+) again\. A clear photo in good light, or the original file from your employer or your bank, usually works\.$/,
      function (m) {
        var name = koDoc(m[1]);
        return name === null ? null
          : name + "를 다시 보내 주세요. 밝은 곳에서 또렷하게 찍은 사진이나, 고용주 또는 은행에서 받은 " +
            "원본 파일이면 대개 됩니다.";
      }],

    // _r_gig_uncorroborated: 뒷받침 자료가 없는 긱 수입
    [/^Your gig earnings statement (?:covers (.+?)|is in your file)\. It is the only paper you gave us that shows this money\. It comes from you, so on its own it does not confirm the amount\. We still counted this money in your yearly total, because leaving it out would be its own kind of wrong\. We are telling the housing worker that no other paper supports it\.$/,
      function (m) {
        return (m[1] ? "긱 수입 명세서는 " + koDate(m[1]) + "을 담고 있습니다. "
                     : "긱 수입 명세서가 제출하신 서류에 있습니다. ") +
               "이 돈을 보여주는 자료는 이것 하나뿐입니다. 본인이 만든 자료이므로, 이것만으로는 금액이 " +
               "확인되지 않습니다. 그래도 이 돈을 연 소득 합계에 넣었습니다. 빼는 것 또한 사실과 " +
               "달라지기 때문입니다. 이를 뒷받침하는 다른 자료가 없다는 사실은 주택 담당자에게 알립니다.";
      }],

    // _r_correction_not_used / _r_correction_in_use
    [/^Check (.+)$/, function (m) {
      var where = koWhere(m[1]);
      return where === null ? null : where + "를 확인해 주세요";
    }],
    [/^(?:You changed the total pay on this stub to (.+?)\. |You changed a number on this stub\. )(?:The other numbers on the same stub add up to a different amount: (.+?) hours at (.+?) an hour comes to (.+?)\. |The other numbers on the same stub add up to a different amount\. )Because the two do not match, we could not tell which one is your regular pay\. We left this stub out when we worked out your yearly income\. We saved your change, and a housing worker can see it\.$/,
      function (m) {
        return (m[1] ? "이 명세서의 총 급여를 " + m[1] + " 으로 고치셨습니다. "
                     : "이 명세서의 숫자를 고치셨습니다. ") +
               (m[2] ? "같은 명세서의 다른 숫자들은 다른 금액이 됩니다. " + m[2] + "시간 × 시급 " +
                       m[3] + " 은 " + m[4] + " 입니다. "
                     : "같은 명세서의 다른 숫자들은 다른 금액이 됩니다. ") +
               "둘이 맞지 않아서, 어느 쪽이 정기 급여인지 알 수 없었습니다. 연 소득을 계산할 때 이 " +
               "명세서는 빼 두었습니다. 고치신 내용은 저장되어 있고, 주택 담당자가 볼 수 있습니다.";
      }],
    [/^You corrected a number on (.+)\. After your change, the hours, the hourly rate and the total on that stub agree with each other\. So we used your figure as your regular pay, and your yearly income reflects it\. We are telling the housing worker that this figure came from you rather than from the page, so they can check it against the document\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "의 숫자를 고치셨습니다. 고치신 뒤로 그 명세서의 근무시간, 시급, 총액이 서로 맞습니다. " +
            "그래서 고치신 금액을 정기 급여로 보고 계산했고, 연 소득에도 반영되어 있습니다. 이 숫자가 " +
            "문서가 아니라 본인에게서 나왔다는 사실은 주택 담당자에게 알립니다. 담당자가 문서와 대조할 " +
            "수 있도록 하기 위해서입니다.";
      }],

    // _r_pay_stub_conflict: 한 코드가 네 가지 문장을 만든다
    [/^Your stubs show (.+?)\. On each stub we checked the hours and the hourly rate against the total\. No stub settled which figure is your regular pay\. We will not pick one for you, because picking one would be a guess\. So we did not produce a yearly income figure from your wages\.$/,
      function (m) {
        return "명세서에 적힌 금액은 " + m[1].replace(/ and /g, ", ") + " 입니다. 명세서마다 근무시간과 " +
               "시급을 총액과 대조했습니다. 어느 명세서도 정기 급여가 얼마인지 확정해 주지 못했습니다. " +
               "저희가 하나를 골라 드리지는 않습니다. 고르는 것은 짐작이기 때문입니다. 그래서 임금에서 " +
               "연 소득 금액을 내지 않았습니다.";
      }],
    [/^Your stubs show different totals\. On each stub we checked the hours and the hourly rate against the total\. No stub settled which figure is your regular pay\. We will not pick one for you, because picking one would be a guess\. So we did not produce a yearly income figure from your wages\.$/,
      function () {
        return "명세서마다 총액이 다릅니다. 명세서마다 근무시간과 시급을 총액과 대조했습니다. 어느 " +
               "명세서도 정기 급여가 얼마인지 확정해 주지 못했습니다. 저희가 하나를 골라 드리지는 " +
               "않습니다. 고르는 것은 짐작이기 때문입니다. 그래서 임금에서 연 소득 금액을 내지 않았습니다.";
      }],
    [/^The letter points to (.+?) a year\. Your pay stubs point to (.+?) a year\. We used the figure from your pay stubs, because a stub shows what you were actually paid\. We are telling the housing worker about the gap so they can check it\.$/,
      function (m) {
        return "증명서는 연 " + m[1] + " 을 가리킵니다. 급여명세서는 연 " + m[2] + " 을 가리킵니다. " +
               "명세서는 실제로 받은 금액을 보여주므로, 명세서 쪽 금액을 썼습니다. 두 금액의 차이는 " +
               "주택 담당자에게 알려 확인할 수 있게 합니다.";
      }],
    [/^The numbers on (.+) do not add up$/, function (m) {
      var where = koWhere(m[1]);
      return where === null ? null : where + "의 숫자가 서로 맞지 않습니다";
    }],
    [/^The stub shows a total of (.+?)\. The hours and the hourly rate on the same stub come to a different amount\. We still used the total, because that is what the stub says\. We are telling the housing worker that the two figures do not match\.$/,
      function (m) {
        return "명세서에 적힌 총액은 " + (m[1] === "the total" ? "그 총액" : m[1]) + " 입니다. 같은 " +
               "명세서의 근무시간과 시급으로 계산하면 다른 금액이 나옵니다. 그래도 명세서에 적힌 총액을 " +
               "썼습니다. 명세서가 그렇게 말하고 있기 때문입니다. 두 금액이 맞지 않는다는 사실은 주택 " +
               "담당자에게 알립니다.";
      }],
    [/^One stub shows (.+?)\. Another shows (.+?)\. We used (.+?) as your regular pay, because the hours and the hourly rate on that stub add up to it\. We treated the difference as extra pay for one period only, so we did not count it across the whole year\. If that extra pay comes every time, your yearly figure would be higher than the one we worked out\.$/,
      function (m) {
        return "한 명세서에는 " + m[1] + " 이 적혀 있습니다. 다른 명세서에는 " + m[2] + " 이 적혀 " +
               "있습니다. " + m[3] + " 을 정기 급여로 썼습니다. 그 명세서의 근무시간과 시급을 곱하면 그 " +
               "금액이 나오기 때문입니다. 차액은 한 회차에만 있었던 추가 급여로 보고, 한 해 전체에 " +
               "곱하지 않았습니다. 그 추가 급여가 매번 나온다면, 연 소득은 저희가 계산한 금액보다 " +
               "높아집니다.";
      }],

    // _r_value_not_traceable / _r_income_not_traceable / _r_amount_missing
    [/^We read a number from (.+), but we could not point to the exact spot on the page\. A housing worker has to be able to check every number in your file against the page it came from\. Until they can, we hold this number aside\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "에서 숫자를 읽었지만, 문서의 어느 위치인지 정확히 짚지 못했습니다. 주택 담당자는 " +
            "서류의 모든 숫자를 그 숫자가 나온 문서와 대조할 수 있어야 합니다. 그렇게 되기 전까지 이 " +
            "숫자는 따로 빼 둡니다.";
      }],
    [/^We read a pay amount from (.+), but we could not point a housing worker at the exact spot on the page\. A number nobody can check is a number we will not count, so this one is not in your yearly figure\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "에서 급여 금액을 읽었지만, 문서의 어느 위치인지 주택 담당자에게 정확히 짚어 줄 수 " +
            "없었습니다. 아무도 확인할 수 없는 숫자는 계산에 넣지 않습니다. 그래서 이 금액은 연 소득에 " +
            "들어 있지 않습니다.";
      }],
    [/^We looked at (.+) for an amount before tax and did not find one we could use\. We did not guess at a figure\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "에서 세전 금액을 찾아봤지만, 쓸 수 있는 금액을 찾지 못했습니다. 금액을 짐작하지 않았습니다.";
      }],

    // _r_frequency_not_stated: 앞의 문서 표현은 첫 글자가 대문자로 온다
    [/^To work out a yearly figure we multiply your pay by how often you get it\. (.+) does not say whether you are paid weekly, every two weeks, twice a month, monthly or once a year\. We will not work it out from the dates, because two dates two weeks apart do not prove that every payment is two weeks apart\.$/,
      function (m) {
        var where = koWhere(m[1].charAt(0).toLowerCase() + m[1].slice(1));
        if (where === null) return null;
        return "연 소득을 내려면 급여에 지급 횟수를 곱해야 합니다. " + where + "에는 급여를 주급으로 " +
               "받는지, 2주마다 받는지, 월 2회 받는지, 월급으로 받는지, 연 1회 받는지가 적혀 있지 " +
               "않습니다. 날짜만 보고 추정하지는 않습니다. 2주 간격인 날짜 두 개가 모든 지급이 2주 " +
               "간격이라는 증거는 아니기 때문입니다.";
      }],

    // app.js: "이렇게 쓴 이유" 와 차단된 키
    [/^Why this wording: (.+)$/, function (m) {
      var note = lookup(m[1]);
      return note === null ? null : "이렇게 쓴 이유: " + note;
    }],
    [/^Blocked keys: (\[.*\])$/, function (m) { return "차단된 키: " + m[1]; }],
    // 기준액 답변. 금액과 세대원 수는 데이터라 그대로 둔다.
    [/^(\$[\d,]+) for household size (\d+)\.$/, function (m) {
      return "세대원 " + m[2] + "인 기준 " + m[1] + " 입니다.";
    }],
    // 승인 조건 프레임(예: "승인받으려면 … 얼마")이 붙은 한도 질문에는 api/ask.py 가
    // 무판정 문장을 덧붙인다. 금액·세대원 수는 데이터라 그대로 둔다.
    [/^(\$[\d,]+) for household size (\d+)\. That figure is the frozen limit for that household size, not a statement about any application: a qualified housing professional makes the eligibility determination\.$/,
      function (m) {
        return "세대원 " + m[2] + "인 기준 " + m[1] + " 입니다. 이 금액은 해당 세대원 수의 동결된 " +
               "기준액일 뿐, 어떤 신청에 대한 판단이 아닙니다. 자격 판정은 자격을 갖춘 주택 " +
               "전문가가 내립니다.";
      }],
    [/^PDF page (\d+)$/, function (m) { return "PDF " + m[1] + "쪽"; }],

    // 진행 안내와 이동 (2페이지 구조)
    [/^Page (\d+) of 2\.\s*(.*)$/, function (m) {
      return "2페이지 중 " + m[1] + "페이지. " + (lookup(m[2]) || m[2]);
    }],
    // 페이지 레일의 링크: "1. Your documents" 처럼 번호가 같은 텍스트 노드에 붙는다.
    [/^([12])\. (.+)$/, function (m) {
      var name = lookup(m[2]);
      return name === null ? null : m[1] + ". " + name;
    }],
    [/^Go to page (\d+)$/, function (m) { return m[1] + "페이지로 가기"; }],
    // (옛 6단계 이동 문구 — 화면에서는 사라졌지만, 지우는 것은 "추가만"이 아니다)
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
    [/^There are (\d+) open items on this page$/, function (m) {
      return "이 페이지에 남은 항목이 " + m[1] + "개 있습니다";
    }],
    [/^(\d+) things here need a person to look at them$/, function (m) {
      return "여기, 사람이 봐야 할 것이 " + m[1] + "개 있습니다";
    }],
    // 2페이지의 요약 우선 접기와 집계 문장
    [/^Present \((\d+)\) — show these items$/, function (m) {
      return "있음 (" + m[1] + ") — 항목 펼치기";
    }],
    [/^(\d+) thing\(s\) still open — each one is listed above with what to do about it\.\s*$/, function (m) {
      return "아직 남은 것이 " + m[1] + "건 있습니다 — 각각 무엇을 하면 되는지 위에 적혀 있습니다. ";
    }],
    [/^About (.+)$/, function (m) {
      var name = lookup(m[1]);
      return name === null ? null : name + "에 대하여";
    }],
    [/^Frozen 60% threshold: (.+) · effective date (.+) · frozen event date (.+)$/, function (m) {
      return "동결된 60% 기준액: " + (lookup(m[1]) || m[1]) + " · 시행일 " + m[2] +
             " · 동결 기준일 " + m[3];
    }],
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
               "기술 세부사항에 그대로 보관되어 있습니다.";
      }],
    [/^(\d+) separate checks raised this one item\. Each check is listed in full under Technical details\.$/,
      function (m) {
        return "서로 다른 검사 " + m[1] + "건이 이 한 항목을 제기했습니다. 각 검사는 " +
               "기술 세부사항에 전부 나열되어 있습니다.";
      }],
    // U6: 영어 제목이 이 한국어를 따라 "Things we did not say" 로 바뀌었다. 한국어는 그대로.
    [/^Things we did not say \((\d+)\)$/, function (m) { return "말하지 않은 것 (" + m[1] + ")"; }],
    // U10: "이 문서에 N개 값이 남았습니다" 카드 본문. N 과 항목 이름은 그대로 둔다.
    // ── 기대 필드의 부재: 문서 관점 안내와 부재 확인 (app.js absenceNotice) ────
    // 문서 종류와 항목 이름은 사전에서 찾아 옮기고, 없으면 영어 그대로 둔다 —
    // 반쪽짜리 명사보다는 온전한 문장 안의 영어 명사가 낫다.
    [/^An? (.+?) usually shows (.+?)\. We did not find one on this document\. The document may be incomplete, or printed in a way we cannot read\.$/,
      function (m) {
        return "보통 " + (lookup(m[1]) || m[1]) + "에는 " + (lookup(m[2]) || m[2]) + " 항목이 " +
               "있습니다. 이 문서에서는 찾지 못했습니다. 문서가 불완전하거나, 저희가 읽을 수 " +
               "없는 방식으로 인쇄되었을 수 있습니다.";
      }],
    [/^If you can, ask (.+?) for a version that shows it — or confirm below that this document really does not show it\.$/,
      function (m) {
        return "가능하시면 " + (lookup(m[1]) || m[1]) + "에 이 값이 보이는 문서를 요청하세요 — " +
               "또는 이 문서에 정말로 이 값이 없다는 것을 아래에서 확인해 주세요.";
      }],
    [/^You checked this(?: on (.+?))?: not shown on this document\.$/, function (m) {
      return (m[1] ? koDate(m[1]) + "에 " : "") + "직접 확인하셨습니다: 이 문서에는 이 값이 없습니다.";
    }],
    [/^Confirm that (\S+) is not shown on (\S+)$/, function (m) {
      return m[2] + " 의 " + m[1] + " 이(가) 이 문서에 없음을 확인";
    }],
    [/^Withdraw the absence check for (\S+) on (\S+)$/, function (m) {
      return m[2] + " 의 " + m[1] + " 에 대한 부재 확인을 철회";
    }],
    [/^(\S+) on (\S+) is checked: not shown on this document\. Nothing else changed, and you can undo this\.$/,
      function (m) {
        return m[2] + " 의 " + m[1] + " — 이 문서에 없음으로 확인했습니다. 다른 것은 아무것도 " +
               "바뀌지 않았고, 되돌릴 수 있습니다.";
      }],
    [/^(\S+) on (\S+) is no longer marked as checked\. It is back to being only a value the machine could not read\.$/,
      function (m) {
        return m[2] + " 의 " + m[1] + " 은(는) 더 이상 확인된 것으로 표시되지 않습니다. 기계가 " +
               "읽지 못한 값이라는 상태로만 돌아갔습니다.";
      }],
    [/^That check could not be recorded: (.+)$/, function (m) {
      return "확인을 기록하지 못했습니다: " + (lookup(m[1]) || m[1]);
    }],

    [/^You have (\d+) value\(s\) left on this document that only the machine has read: (.+)\. Confirming them together records that you compared each one against the page shown above and found it right\. It changes none of the values\. Anything you are unsure about, leave — you can confirm the others one at a time\.$/,
      function (m) {
        return "이 문서에는 기계만 읽은 값이 " + m[1] + "개 남아 있습니다: " + m[2] + ". 이것들을 함께 " +
               "확인하면, 위에 표시된 페이지와 하나하나 대조해 맞다고 확인하셨다는 사실이 기록됩니다. " +
               "값은 하나도 바뀌지 않습니다. 확실하지 않은 것은 남겨 두세요 — 나머지는 하나씩 확인하실 수 있습니다.";
      }],
    // U10: 확인 카운터. 강조 부분(숫자 보간)과 꼬리 문장을 각각 옮긴다.
    [/^(\d+) of (\d+) read values checked by you\.\s*$/, function (m) {
      return "읽어낸 값 " + m[2] + "개 중 " + m[1] + "개를 당신이 확인했습니다. ";
    }],
    [/^Checking is optional and nothing here is wrong\. Whatever you leave unchecked still travels with your file, marked as read by the machine but not yet confirmed by you, and a person can review it either way\.( (\d+) value\(s\) could not be read at all — those need a person to supply them\.)?( For (\d+) of them, you checked the page and confirmed the document does not show the value\.)?$/,
      function (m) {
        var base = "확인은 선택 사항이고, 여기에 잘못된 것은 없습니다. 확인하지 않고 두신 것도 " +
                   "기계가 읽었지만 아직 당신이 확인하지는 않은 것으로 표시되어 파일과 함께 그대로 " +
                   "전달되며, 사람이 어느 쪽이든 검토할 수 있습니다.";
        if (m[2]) {
          base += " " + m[2] + "개 값은 전혀 읽을 수 없었습니다 — 그것들은 사람이 채워 넣어야 합니다.";
        }
        if (m[4]) {
          base += " 그중 " + m[4] + "개는 페이지를 보고 이 문서에 그 값이 없다는 것을 직접 확인하셨습니다.";
        }
        return base;
      }],
    // U8: 이름을 자신 있게 읽지 못했을 때, 이름이 있는 자리에 문장으로 알린다.
    [/^We may not have read your name correctly\. It reads “(.+?)”, but we are not sure\. Check this row first, and fix it here if it is wrong\.$/,
      function (m) {
        return "성함을 정확히 읽지 못했을 수 있습니다. “" + m[1] + "”로 읽었지만 확신하지 못합니다. " +
               "이 행을 먼저 확인하시고, 틀렸으면 여기서 바로잡아 주세요.";
      }],
    // R26: U8 문장의 업로드 변형 — 업로드 표에는 고칠 컨트롤이 없어서 꼬리가 다르다.
    [/^We may not have read your name correctly\. It reads “(.+?)”, but we are not sure\. Check it against the page shown here\. If it is wrong, the person who reviews this document goes by the page, not by our reading\.$/,
      function (m) {
        return "성함을 정확히 읽지 못했을 수 있습니다. “" + m[1] + "”로 읽었지만 확신하지 못합니다. " +
               "여기 보이는 페이지와 대조해 확인해 주세요. 틀렸더라도, 이 문서를 검토하는 사람은 " +
               "저희의 판독이 아니라 페이지를 기준으로 봅니다.";
      }],
    // R26: 업로드 패널의 날짜 기권 다음 걸음 — 발급처가 문장 안에 끼워진다.
    [/^Ask (.+?) for a copy dated to the day, or tell the person who reviews it the exact date\.$/,
      function (m) {
        return (lookup(m[1]) || m[1]) + "에 일(日)까지 적힌 사본을 요청하시거나, 검토하는 사람에게 " +
               "정확한 날짜를 알려 주세요.";
      }],
    [/^Ask (.+?) for a copy that shows the date, or hand this one to a person to read\.$/,
      function (m) {
        return (lookup(m[1]) || m[1]) + "에 날짜가 보이는 사본을 요청하시거나, 이 문서를 사람에게 " +
               "건네 읽게 해 주세요.";
      }],
    // R26: 숫자·날짜가 박힌 resolve 문장들.
    [/^a reviewer supplies the published 60% limit for household size (\d+), with its source$/,
      function (m) {
        return "검토자가 세대원 " + m[1] + "인에 대한 공표된 60% 상한을 출처와 함께 제공하면 됩니다";
      }],
    [/^ask the employer for a letter dated on or after (\d{4}-\d{2}-\d{2}) and upload it$/,
      function (m) {
        return "고용주에게 " + m[1] + " 이후 날짜의 증명서를 받아 올리면 됩니다";
      }],
    [/^supply the documents for the household in question$/, function () {
      return "해당 세대의 서류를 내 주시면 됩니다";
    }],
    [/^supply the documents for (\S+)$/, function (m) {
      return m[1] + " 의 서류를 내 주시면 됩니다";
    }],
    [/^ask about a household size from (\d+) to (\d+)$/, function (m) {
      return "세대원 수 " + m[1] + "명에서 " + m[2] + "명 사이에 대해 물어보시면 됩니다";
    }],
    [/^Reasons this needs review \((\d+)\)$/, function (m) {
      return "검토가 필요한 이유 (" + m[1] + ")";
    }],
    // 점검 목록 구역 제목: "Missing (2)" 처럼 상태어 + 개수
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
      return m[1] + " 에서 추출한 값입니다. 항목 이름을 고르면 문서상의 근거 위치가 강조됩니다.";
    }],
    [/^Inputs to (.+)$/, function (m) { return (lookup(m[1]) || m[1]) + " 의 입력값"; }],
    [/^Measurements for (.+)$/, function (m) { return (lookup(m[1]) || m[1]) + " 측정값"; }],
    [/^Measured at (.+)\.$/, function (m) { return m[1] + " 에 측정함."; }],

    // 데이터 출처 줄 (엔진 sha·ruleset 은 빌드 메타데이터라 손대지 않는다)
    [/^Data source: (.+)$/, function (m) { return "데이터 출처: " + (lookup(m[1]) || m[1]); }],
    // 웹의 origin 은 "출처"가 아니라 "주소"다. 인용의 출처(Source)와 같은 말로 옮기면
    // "데이터 출처: 이 출처 의 …" 처럼 같은 낱말이 겹쳐 읽는 사람을 멈추게 한다.
    // apiBase 가 빈 문자열일 때 app.js 가 넣는 "this origin" 은 주소값이 아니라
    // 문장이므로 옮기고, 실제 주소가 들어오면 데이터이므로 그대로 둔다.
    [/^Live API at (.+) \(same shapes as the fixtures\)$/, function (m) {
      return (m[1] === "this origin"
        ? "이 페이지와 같은 주소의 실시간 API"
        : m[1] + " 의 실시간 API") + " (고정 데이터와 같은 형태)";
    }],

    // 세대 선택과 확인 화면
    [/^(HH-\d+) — (\d+) documents$/, function (m) { return m[1] + " — 서류 " + m[2] + "건"; }],
    [/^(HH-\d+) — (\d+) documents \(no bundled report\)$/, function (m) {
      return m[1] + " — 서류 " + m[2] + "건 (번들된 보고서 없음)";
    }],
    [/^(HH-\d+) · (\d+) documents$/, function (m) { return m[1] + " · 서류 " + m[2] + "건"; }],
    [/^(\d+) values, each one traced to a box on a page$/, function (m) {
      return "값 " + m[1] + "개. 각각이 문서상의 한 위치까지 추적됩니다";
    }],
    [/^(\d+) item\(s\): (.+)$/, function (m) {
      return m[1] + "개 항목: " + m[2].split(", ").map(function (label) {
        return lookup(label) || label;
      }).join(", ");
    }],
    [/^(\d+) thing\(s\) we did not say and (\d+) reason\(s\) this needs review\. All of them are listed in full under “What this system is unsure about”, and all of them travel with your packet\.$/,
      function (m) {
        return "말하지 않은 것 " + m[1] + "건과 검토가 필요한 이유 " + m[2] + "건. 모두 “이 시스템이 확신하지 못하는 것”" +
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
    [/^Only a person can decide that — here is what we can tell you\. (.+)$/, function (m) {
      return "그 판단은 사람만 할 수 있습니다 — 저희가 알려 드릴 수 있는 것은 이렇습니다. " +
             (lookup(m[1]) || m[1]);
    }],
    [/^Abstained — no answer given\. (.+)$/, function (m) {
      return "답하지 않았습니다 — 답을 내지 않았습니다. " + (lookup(m[1]) || m[1]);
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
      }],

    // ══ app.js: 규칙 id 를 근거로 연결한 링크 글자 ══════════════════════════════
    // 두 모양이 있다. 외부 출처가 있으면 "— <출처 위치> (<호스트>)", 없으면
    // "— <출처 위치>, set by this challenge itself (no outside source)".
    // 출처 위치 이름은 우리가 붙인 라벨이므로 옮기고, 호스트는 주소이므로 두고,
    // 법령 인용("26 CFR 1.42-5")은 사전에 없으므로 저절로 영어로 남는다 —
    // 번역된 법령 번호는 그 법령을 가리키지 못한다.
    [/^PDF page (\d+)$/, function (m) { return "PDF " + m[1] + "쪽"; }],
    [/^— (.+) \(([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\)$/, function (m) {
      var where = lookup(m[1]);
      return where === null ? null : "— " + where + " (" + m[2] + ")";
    }],
    [/^— (.+), set by this challenge itself \(no outside source\)$/, function (m) {
      var where = lookup(m[1]);
      return where === null ? null
        : "— " + where + ". 이 과제가 스스로 정한 것입니다 (외부 출처 없음)";
    }],
    [/^— set by this challenge itself \(no outside source\)$/, function () {
      return "— 이 과제가 스스로 정한 것입니다 (외부 출처 없음)";
    }],
    [/^— (?:(.+), )?authority: (.+) \(no outside source\)$/, function (m) {
      var who = lookup(m[2]);
      if (who === null) return null;
      var where = m[1] ? lookup(m[1]) : null;
      if (m[1] && where === null) return null;
      return "— " + (where ? where + ". " : "") + "근거 기관: " + who + " (외부 출처 없음)";
    }],

    // ══ api/plain.py: 짧게 다시 쓰인 카드 본문 ═════════════════════════════════
    // 아래 규칙들은 평문 계층이 문장을 줄여 다시 쓰면서 새로 생긴 짝이다. 예전
    // 문장을 겨냥한 위쪽 규칙들은 영어가 바뀌어 더 이상 걸리지 않지만, 지우지 않고
    // 둔다 — 걸리지 않는 규칙은 조용히 지나갈 뿐이고, 문구가 되돌아갈 때를 위한
    // 기록이기도 하다.

    // _r_item_present
    [/^It is in your file(?:, dated (.+?),)? and recent enough to use\.$/, function (m) {
      return "제출하신 서류 안에 있고" + (m[1] ? ", 날짜는 " + koDate(m[1]) + "이며" : "") +
             ", 쓸 수 있을 만큼 최근 것입니다.";
    }],

    // _r_required_missing
    [/^Your file does not have an? (.+) in it yet, and a housing worker needs it before they can start reading your file\.$/,
      function (m) {
        var name = koDoc(m[1]);
        return name === null ? null
          : "제출하신 서류에 아직 " + name + "가 없습니다. 주택 담당자가 검토를 시작하려면 이 서류가 있어야 합니다.";
      }],

    // _r_not_current
    [/^It is dated (?:(.+?), which is before the cut-off|before the cut-off)\. One out-of-date paper holds up your whole file until someone replaces it, even when nothing is wrong with the rest of it\.$/,
      function (m) {
        return (m[1] ? "날짜는 " + koDate(m[1]) + "이고, 기준일보다 앞섭니다. " : "기준일보다 앞선 날짜입니다. ") +
               "기한이 지난 서류가 하나만 있어도, 나머지에 아무 문제가 없더라도 누군가 새 서류로 바꿀 때까지 전체 검토가 멈춥니다.";
      }],

    // _r_undatable
    [/^(?:It shows (.+?), but not which day of the month\.|It does not show which day of the month it covers\.) We need the day to tell whether the paper is recent enough, and we will not guess one, because a guessed date could put your paper on the wrong side of the line\.$/,
      function (m) {
        return (m[1] ? koDate(m[1]) + "까지만 적혀 있고, 며칠인지는 적혀 있지 않습니다. "
                     : "며칠자를 담고 있는지가 적혀 있지 않습니다. ") +
               "서류가 충분히 최근 것인지 따지려면 날짜가 필요합니다. 그리고 날짜를 지어내지는 않습니다. " +
               "지어낸 날짜 때문에 서류가 기준선의 반대편에 놓일 수 있기 때문입니다.";
      }],

    // _r_unreadable
    [/^Nothing on this (.+) came through clearly enough for us to use, and we did not guess at what it says\. That is a problem with the file we received, not with you or with your paperwork\.$/,
      function (m) {
        var name = koDoc(m[1]);
        return name === null ? null
          : "이 " + name + "에서 쓸 수 있을 만큼 또렷하게 읽힌 내용이 없고, 무엇이 적혀 있는지 짐작하지 " +
            "않았습니다. 받은 파일의 문제이지, 당신이나 당신의 서류 문제가 아닙니다.";
      }],

    // _r_gig_uncorroborated
    // ⚠ "그래도 전액 연 소득 합계에 넣었다"가 반드시 남아야 한다. 이 문장이 빠지면
    //   뒷받침 자료가 없다는 말이 "그래서 빼 두었다"로 읽히는데, 그것은 거짓이다.
    [/^Your gig earnings statement (?:covers (.+?)|is in your file), and it is the only paper you gave us that shows this money, so nothing independent confirms the amount\. We still counted this money in full in your yearly total, and told the housing worker that no other paper supports it\.$/,
      function (m) {
        return (m[1] ? "긱 수입 명세서는 " + koDate(m[1]) + "을 담고 있고, "
                     : "긱 수입 명세서가 제출하신 서류에 있고, ") +
               "이 돈을 보여주는 자료는 이것 하나뿐이어서 금액을 따로 확인해 주는 자료가 없습니다. " +
               "그래도 이 돈은 연 소득 합계에 전액 넣었고, 이를 뒷받침하는 다른 자료가 없다는 사실은 " +
               "주택 담당자에게 알렸습니다.";
      }],

    // _r_value_not_traceable
    [/^We read a number from (.+), but we could not point to the exact spot on the page\. A housing worker has to be able to check every number in your file against the page it came from, so until they can, we hold this one aside\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "에서 숫자를 읽었지만, 문서상의 정확한 자리를 가리키지 못했습니다. 주택 담당자는 " +
            "서류의 모든 숫자를 그것이 나온 문서와 대조할 수 있어야 하므로, 그렇게 될 때까지 이 숫자는 " +
            "따로 빼 둡니다.";
      }],

    // _r_correction_not_used
    [/^(?:You changed the total pay on this stub to (.+?), |You changed a number on this stub, )but (?:its own hours and hourly rate, (.+?) hours at (.+?) an hour, come to (.+?)|the other numbers on the same stub come to a different amount)\. Because the two do not match, we left this stub out when we worked out your yearly income\. Your change is saved, and a housing worker can see it\.$/,
      function (m) {
        return (m[1] ? "이 명세서의 총 급여를 " + m[1] + " 으로 고치셨습니다. "
                     : "이 명세서의 숫자를 고치셨습니다. ") +
               (m[2] ? "그런데 같은 명세서의 근무시간과 시급, " + m[2] + "시간 × 시급 " + m[3] + " 은 " +
                       m[4] + " 이 됩니다. "
                     : "그런데 같은 명세서의 다른 숫자들은 다른 금액이 됩니다. ") +
               "둘이 맞지 않아서, 연 소득을 계산할 때 이 명세서는 빼 두었습니다. 고치신 내용은 저장되어 " +
               "있고, 주택 담당자가 볼 수 있습니다.";
      }],

    // _r_correction_in_use
    [/^After your change, the hours, the hourly rate and the total on (.+) agree with each other, so we used your figure as your regular pay\. We told the housing worker it came from you rather than from the page, so they can check it\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : "고치신 뒤로 " + where + "의 근무시간, 시급, 총액이 서로 맞습니다. 그래서 고치신 금액을 정기 " +
            "급여로 보고 계산했습니다. 이 숫자가 문서가 아니라 본인에게서 나왔다는 사실은 주택 담당자에게 " +
            "알려, 담당자가 대조할 수 있게 했습니다.";
      }],

    // _r_pay_stub_conflict (a) — 어느 명세서도 정기 급여를 확정하지 못한 경우
    [/^Your stubs show (.+?)\. On no stub do the hours and the hourly rate settle which figure is your regular pay, so rather than guess we left your wages out of the yearly income figure\.$/,
      function (m) {
        return "명세서에 적힌 금액은 " + m[1].replace(/ and /g, ", ") + " 입니다. 어느 명세서에서도 " +
               "근무시간과 시급이 정기 급여가 얼마인지를 확정해 주지 못했습니다. 그래서 짐작하는 대신, " +
               "임금을 연 소득 금액에서 빼 두었습니다.";
      }],

    // _r_pay_stub_conflict (b) — 재직증명서와 명세서가 어긋남
    [/^The letter points to (.+?) a year and your pay stubs point to (.+?)\. We used the stubs, because a stub shows what you were actually paid, and we are telling the housing worker about the gap\.$/,
      function (m) {
        return "증명서는 연 " + m[1] + " 을 가리키고, 급여명세서는 " + m[2] + " 을 가리킵니다. 명세서는 " +
               "실제로 받으신 금액을 보여주므로 명세서 쪽을 썼습니다. 두 금액의 차이는 주택 담당자에게 " +
               "알립니다.";
      }],

    // _r_pay_stub_conflict (c) — 한 명세서 안의 숫자가 서로 안 맞음
    [/^The stub shows a total of (.+?), but the hours and the hourly rate on the same stub come to a different amount\. We used the stated total and told the housing worker that the two figures do not match\.$/,
      function (m) {
        return "명세서에 적힌 총액은 " + (m[1] === "the total" ? "그 총액" : m[1]) + " 인데, 같은 " +
               "명세서의 근무시간과 시급으로 계산하면 다른 금액이 나옵니다. 적혀 있는 총액을 썼고, 두 " +
               "금액이 맞지 않는다는 사실은 주택 담당자에게 알렸습니다.";
      }],

    // _r_pay_stub_conflict (d) — 초과분을 한 회차에만 둔 경우
    [/^One stub shows (.+?) and another shows (.+?)\. We used (.+?) as your regular pay, because the hours and the hourly rate on that stub add up to it, and we treated the difference as extra pay for one period rather than counting it across the year\. If that extra pay comes every time, your yearly figure would be higher\.$/,
      function (m) {
        return "한 명세서에는 " + m[1] + " 이, 다른 명세서에는 " + m[2] + " 이 적혀 있습니다. " + m[3] +
               " 을 정기 급여로 썼습니다. 그 명세서의 근무시간과 시급을 곱하면 그 금액이 나오기 " +
               "때문입니다. 차액은 한 해 전체에 곱하지 않고 한 회차에만 있었던 추가 급여로 보았습니다. " +
               "그 추가 급여가 매번 나온다면 연 소득은 이보다 높아집니다.";
      }],

    // _r_frequency_not_stated / _r_amount_missing / _r_income_not_traceable
    [/^To work out a yearly figure we multiply your pay by how often you get it, and that is not stated on (.+)\. We will not read it off the dates, because two payments two weeks apart do not prove that every payment is\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : "연 소득을 내려면 급여에 지급 횟수를 곱해야 하는데, " + where + "에 그것이 적혀 있지 " +
            "않습니다. 날짜를 보고 짐작하지는 않습니다. 두 번의 지급이 2주 간격이라고 해서 매번 그렇다는 " +
            "뜻은 아니기 때문입니다.";
      }],
    [/^We looked at (.+) for an amount before tax, did not find one we could use, and did not guess at a figure\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "에서 세전 금액을 찾아보았지만 쓸 수 있는 것을 찾지 못했고, 금액을 지어내지 " +
            "않았습니다.";
      }],
    [/^We read a pay amount from (.+), but we could not point a housing worker at the exact spot on the page\. A number nobody can check is one we will not count, so it is not in your yearly figure\.$/,
      function (m) {
        var where = koWhere(m[1]);
        return where === null ? null
          : where + "에서 급여 금액을 읽었지만, 주택 담당자에게 문서상의 정확한 자리를 가리켜 드리지 " +
            "못했습니다. 아무도 대조할 수 없는 숫자는 세지 않으므로, 이 금액은 연 소득에 들어 있지 " +
            "않습니다.";
      }],

    // 기준 문장이 홀로 놓이는 자리 (PlainMessage.basis)
    [/^A paper counts as recent only if it is dated .+ or later\. That is the \d+-day rule this project follows, counting back from .+\.$/,
      function (m) { return koCurrency(m[0]); }],

    // ══ api/upload.py: 데이터가 박힌 거절 사유 ═════════════════════════════════
    [/^We do not know how to read a document of type '(.+?)'\. We can read: (.+)\.$/, function (m) {
      var kinds = m[2].split(", ").map(function (k) { return lookup(k) || k; }).join(", ");
      return "'" + m[1] + "' 종류의 문서는 읽을 줄 모릅니다. 읽을 수 있는 것은 " + kinds + " 입니다.";
    }],
    [/^That file is (.+?) MB\. The limit is (\d+) MB, because an uploaded document is held in memory for this session only and never written to disk\.$/,
      function (m) {
        return "그 파일은 " + m[1] + " MB 입니다. 한도는 " + m[2] + " MB 입니다. 올리신 문서는 이번 " +
               "세션의 메모리에만 두고 디스크에 기록하지 않기 때문입니다.";
      }],
    [/^This service reads PDF documents only\. The browser sent that file as '(.+)'\.$/, function (m) {
      return "이 서비스는 PDF 문서만 읽습니다. 브라우저는 그 파일을 '" + m[1] + "' 로 보냈습니다.";
    }],
    [/^We could not open that PDF \((.+?)\)\. It may be damaged or password-protected\.$/, function (m) {
      return "그 PDF 를 열지 못했습니다 (" + m[1] + "). 파일이 손상되었거나 암호가 걸려 있을 수 있습니다.";
    }],
    [/^The server could not accept that file \(HTTP (\d+)\)\.$/, function (m) {
      return "서버가 그 파일을 받아들이지 못했습니다 (HTTP " + m[1] + ").";
    }],

    // ══ app.js: 업로드 결과와 세션 수명에서 데이터가 박힌 문장 ══════════════════
    [/^(.+) — the document you uploaded$/, function (m) {
      var kind = lookup(m[1]);
      return kind === null ? null : kind + " — 올리신 문서";
    }],
    [/^Read (\d+) of (\d+) fields from the uploaded document\.$/, function (m) {
      return "올리신 문서에서 " + m[2] + "개 항목 중 " + m[1] + "개를 읽었습니다.";
    }],
    [/^Read (\d+) of (\d+) fields from (\d+) documents in the uploaded file\.$/, function (m) {
      return "올리신 파일 안 " + m[3] + "개 문서에서 " + m[2] + "개 항목 중 " + m[1] + "개를 읽었습니다.";
    }],
    // 하위 문서 제목: "<종류> · page N" / "<종류> · pages N–M" (종류는 사전에 있다).
    [/^(.+) · page (\d+)$/, function (m) {
      var kind = lookup(m[1]);
      return kind === null ? null : kind + " · " + m[2] + "페이지";
    }],
    [/^(.+) · pages (\d+)–(\d+)$/, function (m) {
      var kind = lookup(m[1]);
      return kind === null ? null : kind + " · " + m[2] + "–" + m[3] + "페이지";
    }],

    // ══ 결합 문서: 여러 페이지·여러 하위 문서 (번호·파일명은 데이터) ═══════════
    // 하위 문서 하나를 사람이 고른 종류로 다시 읽기 시작할 때의 알림.
    [/^Re-reading this document as (.+)…$/, function (m) {
      var kind = lookup(m[1]);
      return kind === null ? null : "이 문서를 " + kind + "(으)로 다시 읽는 중…";
    }],
    // 파일 요약 제목: "N documents in one file — 파일명".
    [/^(\d+) documents in one file — (.+)$/, function (m) {
      return m[2] + " — 한 파일 안 " + m[1] + "개 문서";
    }],
    // 여러 페이지를 그릴 때 각 페이지 표지: "Page N of 파일명".
    [/^Page (\d+) of (.+\.pdf)$/, function (m) {
      return m[2] + "의 " + m[1] + "페이지";
    }],
    // 페이지 이미지의 대체 텍스트(접근성): "Rendered page N of 파일명".
    [/^Rendered page (\d+) of (.+)$/, function (m) {
      return m[2] + "의 " + m[1] + "페이지 (서버가 그린 이미지)";
    }],
    // 페이지 캡션(페이지 번호가 박힌다). 기존 "Page 1 as rendered…" DICT 를 모든 N 으로.
    [/^Page (\d+) as rendered by the server\. Each rectangle is the box the value was read from; the same coordinates are listed as text in the table below\.$/,
      function (m) {
        return "서버가 그린 " + m[1] + "페이지입니다. 각 사각형은 값을 읽어낸 근거 위치이고, " +
               "같은 좌표가 아래 표에 글자로 적혀 있습니다.";
      }],
    // item 3: app.js 가정 배너의 설명 문장(종류가 박힌다).
    [/^This page did not print a title we recognise, so we did not stop to ask what it is — we read it as a (.+), the most common income document, and showed you the result below\.$/,
      function (m) {
        var kind = lookup(m[1]) || m[1];
        return "이 페이지에는 저희가 알아보는 제목이 인쇄되어 있지 않아, 무엇인지 여쭙느라 멈추지 " +
               "않고 " + kind + "(으)로 읽어 아래에 결과를 보여 드렸습니다. — 가장 흔한 소득 문서입니다.";
      }],
    // item 3: api/upload.py 가정 limits 줄(종류는 원문 그대로 pay_stub 등).
    [/^This page did not print a title we recognise, so we did not ask what it is — we read it as a (\w+), the most common income document, and showed you the result\. If that is not what this is, change the kind above and we will read it again that way\.$/,
      function (m) {
        return "이 페이지에는 저희가 알아보는 제목이 인쇄되어 있지 않아, 무엇인지 묻지 않고 " + m[1] +
               "(으)로 읽어 결과를 보여 드렸습니다 — 가장 흔한 소득 문서입니다. 이 문서가 그 종류가 " +
               "아니라면 위에서 종류를 바꿔 주시면 그 종류로 다시 읽겠습니다.";
      }],
    // 세션 업로드 상한 초과(하위 문서 개수만큼 필요). 숫자 셋은 데이터.
    [/^This session already holds (\d+) of (\d+) uploaded documents, and this file adds (\d+) more, which is over the ceiling — every one stays in this session's memory\. You can open the file made of the ones you have, remove one, or delete the session at the end of page 2 and start again\.$/,
      function (m) {
        return "이 세션은 이미 올린 문서 " + m[2] + "개 중 " + m[1] + "개를 들고 있고, 이 파일이 " +
               m[3] + "개를 더해 상한을 넘습니다 — 하나하나 모두 이 세션의 메모리에 남습니다. 지금 " +
               "가진 문서로 이룬 파일을 열거나, 하나를 지우거나, 2페이지 끝에서 세션을 지우고 다시 " +
               "시작하실 수 있습니다.";
      }],
    [/^Session (\S+) no longer exists in the API process\. Rather than tell you that and stop, the page then asked the server for this household again using the id it had just destroyed\.$/,
      function (m) {
        return "세션 " + m[1] + " 은 API 프로세스에 더 이상 없습니다. 그 말만 하고 멈추는 대신, 이 " +
               "화면은 방금 없앤 id 로 같은 세대를 서버에 다시 물어보았습니다.";
      }],
    [/^GET (\S+) with the deleted id answered HTTP (\d+) — (?:nothing left to answer with|expected 404)\.$/,
      function (m) {
        var tail = /expected 404/.test(m[0]) ? " — 404 를 기대했습니다." : " — 답할 것이 남아 있지 않습니다.";
        return "삭제된 id 로 보낸 GET " + m[1] + " 은 HTTP " + m[2] + " 를 돌려주었습니다" + tail;
      }],
    // ⚠ "다른 정정은 그대로 남아 있다"가 빠지면, 하나를 되돌린 것이 전부를 되돌린
    //   것으로 읽힌다. 필드명과 문서 id 는 기계 식별자이므로 옮기지 않는다.
    [/^Correction undone\. (\S+) on (\S+) is back to the extracted value, and any other correction is still in place\.$/,
      function (m) {
        // 조사는 필드명 뒤에 바로 붙이지 않는다. 필드명이 영문 기계 식별자라 받침
        // 유무를 알 수 없어 "이/가" 를 고를 수 없다. "항목" 을 끼워 넣어 피한다.
        return "정정을 되돌렸습니다. " + m[2] + " 의 " + m[1] + " 항목이 추출된 값으로 돌아갔고, " +
               "다른 정정은 그대로 남아 있습니다.";
      }],
    [/^Started again\. (\S+) has been loaded from the pack as a new session\. The deleted session was not restored\.$/,
      function (m) {
        return "다시 시작했습니다. " + m[1] + " 을 팩에서 새 세션으로 불러왔습니다. 삭제한 세션은 " +
               "복구되지 않았습니다.";
      }],
    [/^Chosen file: (.+)$/, function (m) { return "고른 파일: " + m[1]; }],

    // ══ app.js: 성적표 한 줄 요약 (measureSummary) ═════════════════════════════
    // "<항목> <값> · <항목>: 3 entries · <항목>: none found" 모양이다. 항목 이름은
    // 사전에 있고, 숫자는 데이터다. 한 조각이라도 이름을 모르면 줄 전체를 영어로
    // 둔다 — 절반만 한국어인 줄은 읽는 사람을 더 헷갈리게 한다.
    [/^[^·]+(?: · [^·]+)+$/, function (m) {
      var parts = m[0].split(" · ").map(koMeasureSegment);
      for (var i = 0; i < parts.length; i += 1) if (parts[i] === null) return null;
      return parts.join(" · ");
    }],

    // ══ app.js: 업로드 파일과 행 안 편집기 — 숫자·값이 박힌 문장들 ═══════════════
    // 세대 선택 목록의 업로드 파일 행. 개수는 데이터, 나머지가 문장이다.
    [/^Your uploaded documents \((\d+)\)$/, function (m) {
      return "내가 올린 문서 (" + m[1] + ")";
    }],
    [/^Open your uploaded documents \((\d+)\)$/, function (m) {
      return "내가 올린 문서 열기 (" + m[1] + ")";
    }],
    // 정정된 행 옆의 가리킴 기록.
    [/^You pointed at page (\d+) for this value\. The packet carries the spot you marked\.$/,
      function (m) {
        return "이 값의 자리로 페이지 " + m[1] + "을(를) 가리키셨습니다. 표시하신 자리는 서류 묶음에 함께 실립니다.";
      }],
    // 가리킨 영역을 읽어낸 제안. 값은 데이터로 그대로 둔다.
    [/^We read “(.+)” from the area you pointed at\. It is a suggestion — check it against the picture, fix it if it is wrong, then save\.$/,
      function (m) {
        return "가리키신 영역에서 “" + m[1] + "”(이)라고 읽었습니다. 제안일 뿐입니다 — 그림과 대조해 확인하고, 틀렸으면 고친 뒤 저장하세요.";
      }],
    // "처음부터 다시"의 확인 단계. 숫자 셋은 데이터다.
    [/^This clears all your work in this session: (\d+) upload\(s\), (\d+) correction\(s\) and (\d+) confirmation\(s\)\. The prepared example files are not touched\.$/,
      function (m) {
        return "이번 세션에서 하신 일이 모두 지워집니다: 올린 문서 " + m[1] + "건, 정정 " +
               m[2] + "건, 확인 " + m[3] + "건. 준비된 예시 파일들은 건드리지 않습니다.";
      }],

    // ══ 종류 지명: 근거 문장 — 일치한 인쇄 문구는 데이터라 옮기지 않는다 ═══════
    [/^Because the page prints “(.+)” at the top \(page (\d+)\)\.$/, function (m) {
      return "페이지 " + m[2] + " 맨 위에 “" + m[1] + "”(이)라고 인쇄되어 있기 때문입니다.";
    }],
    // api/store.py 가 limits 에 싣는 지명 근거 줄.
    [/^The kind of document was not chosen by you: the page prints “(.+)” at the top, and that is the whole reason it was read as this kind\. If the page is about that kind of document rather than being one, change the kind and read it again\.$/,
      function (m) {
        return "문서 종류는 직접 고르신 것이 아닙니다: 페이지 맨 위에 “" + m[1] + "”(이)라고 " +
               "인쇄되어 있고, 그것이 이 종류로 읽은 이유의 전부입니다. 이 페이지가 그 종류의 " +
               "문서가 아니라 그 종류에 관한 문서라면, 종류를 바꿔 다시 읽어 주세요.";
      }],

    // ══ 단계별 읽기: 개수가 박힌 단계 문장들 ═══════════════════════════════════
    [/^Read the scanned areas instead \((\d+) region\(s\) came back readable\)\. Drawing each one…$/,
      function (m) {
        return "대신 스캔된 영역을 읽었습니다 (읽을 수 있었던 영역 " + m[1] + "곳). 하나씩 그리는 중…";
      }],
    [/^Reading the scanned areas: (\d+) regions\.$/, function (m) {
      return "스캔된 영역을 읽는 중: " + m[1] + "곳.";
    }],
    [/^Done — (\d+) of (\d+) fields read, each drawn where it was found\.$/, function (m) {
      return "끝 — " + m[2] + "개 항목 중 " + m[1] + "개를 읽어, 각각 찾은 자리에 그렸습니다.";
    }],
    [/^Done reading\. (\d+) of (\d+) fields are on screen with their boxes\.$/, function (m) {
      return "읽기가 끝났습니다. " + m[2] + "개 항목 중 " + m[1] + "개가 근거 상자와 함께 화면에 있습니다.";
    }],

    // ══ 문서 한 장 지우기: 남은 개수가 박힌 안내 ═══════════════════════════════
    [/^The document was removed\. (\d+) uploaded document\(s\) remain in this session\.$/,
      function (m) {
        return "문서를 지웠습니다. 이 세션에 올린 문서가 " + m[1] + "건 남아 있습니다.";
      }],

    // ══ 월 단위 날짜의 정직한 삼분법 (달 이름이 문장에 박힌다) ═════════════════
    [/^Current — any day in ([A-Z][a-z]+ \d{4}) falls inside the 60-day window\. The exact day is still not recorded\.$/,
      function (m) {
        return "유효 — " + koDate(m[1]) + "의 어느 날이든 60일 창 안에 듭니다. 정확한 일(日)은 " +
               "여전히 기록되어 있지 않습니다.";
      }],
    [/^Out of date — every day in ([A-Z][a-z]+ \d{4}) falls outside the 60-day window\.$/,
      function (m) {
        return "기한 지남 — " + koDate(m[1]) + "의 모든 날이 60일 창 밖에 있습니다.";
      }],
    [/^Ask (.+?) for a recent copy dated to the day\.$/, function (m) {
      return (lookup(m[1]) || m[1]) + "에 일(日)까지 적힌 최근 사본을 요청하세요.";
    }]
  ];

  /** 성적표 요약 한 조각. app.js::measureSummary 가 만드는 네 가지 모양을 되받는다. */
  function koMeasureSegment(segment) {
    var m, label;
    if ((m = segment.match(/^(.+?): (\d+) entries$/))) {
      label = lookup(m[1]);
      return label === null ? null : label + ": " + m[2] + "건";
    }
    if ((m = segment.match(/^(.+?): (\d+) fields$/))) {
      label = lookup(m[1]);
      return label === null ? null : label + ": " + m[2] + "개 항목";
    }
    if ((m = segment.match(/^(.+?): (.+)$/))) {
      label = lookup(m[1]);
      return label === null ? null : label + ": " + (lookup(m[2]) || m[2]);
    }
    if ((m = segment.match(/^(.+?) (\S+)$/))) {
      label = lookup(m[1]);
      return label === null ? null : label + " " + (lookup(m[2]) || m[2]);
    }
    return null;
  }

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
  //  ⚠ 이 구역은 사전과 달리 **영어 원문이 키가 아니다.** data-i18n-block 속성이 키다.
  //  그래서 영어가 바뀌어도 조회가 빗나가지 않고, 낡은 한국어가 그대로 렌더링된다.
  //  실제로 그렇게 사고가 났다: 의도 분류기가 들어오면서 영어 푸터가 "이 페이지는
  //  외부로 요청하지 않는다"에서 "그것은 이 페이지에 대한 약속이지 시스템 전체에 대한
  //  약속이 아니다"로 고쳐졌는데, 한국어만 옛 주장을 계속 보여 주고 있었다. 검증 가능한
  //  주장만 한다는 것이 이 제품의 논지이므로, 한국어 화면에만 낡은 주장이 남는 것은
  //  그 논지를 스스로 깨는 일이다.
  //
  //  그래서 각 항목은 그때의 영어 원문(`en`)을 함께 들고 있고, 바꿔치기 전에 화면의
  //  영어와 대조한다. 어긋나면 **번역하지 않고 영어를 그대로 둔다.** 틀린 한국어보다
  //  영어가 낫다는 판단이며, 콘솔에 남겨 다음 사람이 알아채게 한다.
  var BLOCKS = {
    "lede-correct": {
      en: "Change a value the system read, and watch the numbers underneath it move — or " +
          "watch the system explain why your correction was not used.",
      ko: [
        "시스템이 읽은 값을 바꾸고, 그 아래 숫자들이 따라 움직이는지 보세요. 또는 그 정정이 왜 쓰이지 ",
        ["em", "않았는지"],
        " 시스템이 설명하는 것을 보세요."
      ]
    },
    "footer-privacy": {
      // U10: 저장된 en 이 실제 HTML 보다 한 문장("?fixtures ...") 길어서 대조가 어긋났고,
      // 그 때문에 이 문단은 한국어 토글에서도 계속 영어로 남아 있었다. 화면의 실제 문단에
      // 맞춰 en 과 ko 를 그 문장 앞에서 끝낸다(그 정보는 "How this works" 에도 있다).
      en: "No external fonts, scripts, images, or analytics. Every request this page makes goes to the " +
          "address in the bar above it and nowhere else; opened as a file, it makes none at all. That is a " +
          "promise about this page, not about the whole system: when the question classifier is switched on, " +
          "the server sends your question sentence to a model provider so it can pick a topic label. What we " +
          "can promise structurally is narrower and harder: no document, no extracted field and no household " +
          "record is ever part of that request. Before your sentence is sent we replace the identifier shapes " +
          "we can recognise, such as an email address, a phone number or a street address. We cannot " +
          "recognise all of them, so a name you type is sent as you typed it.",
      // 영어의 논지 순서를 그대로 지킨다: ① 페이지는 외부로 나가지 않는다 → ② 그러나 그것은
      // 이 페이지에 대한 약속일 뿐이다 → ③ 대신 좁고 단단한 약속(문서·필드·세대 기록은 절대
      // 나가지 않는다) → ④ 식별자 치환은 하되 완전하지 않다.
      // "완전히"·"모든 개인정보" 같은 완전성 어휘를 쓰지 않는다. 이 문단의 일은 넓은 약속을
      // 흐리는 것이 아니라 좁은 약속을 분명히 하는 것이다.
      ko: [
        "외부 폰트·스크립트·이미지·분석 도구가 없습니다. 이 화면이 보내는 모든 요청은 위 주소창의 " +
        "주소로만 가고 다른 어디로도 가지 않습니다. 파일로 열면 요청을 아예 보내지 않습니다. " +
        "다만 이것은 이 화면에 대한 약속이지 시스템 전체에 대한 약속이 아닙니다. 질문 분류기가 " +
        "켜져 있으면, 서버가 주제 이름을 고르기 위해 질문 문장을 모델 제공자에게 보냅니다. " +
        "구조로 약속할 수 있는 것은 그보다 좁고 그만큼 단단합니다. 어떤 문서도, 추출된 어떤 항목도, " +
        "세대 기록도 그 요청에 결코 실리지 않습니다. 문장을 보내기 전에 저희가 알아볼 수 있는 " +
        "식별자 형태 — 이메일 주소, 전화번호, 도로명 주소 같은 것 — 는 바꿔 넣습니다. 그러나 모두 " +
        "알아볼 수는 없습니다. 직접 타이핑하신 이름은 적으신 그대로 나갑니다."
      ]
    },
    // U9: 긴 푸터 문단이 "기술 세부사항" 뒤로 접혔고, 그 앞에 한 줄 요약이 남았다.
    "footer-privacy-lead": {
      en: "This page sends nothing to outside servers on its own. When the question " +
          "classifier is switched on, your typed question — and only that — goes to a model " +
          "provider so it can pick a topic; no document, no extracted field and no household " +
          "record ever does.",
      ko: [
        "이 화면은 스스로 외부 서버로 아무것도 보내지 않습니다. 질문 분류기가 켜져 있으면, " +
        "직접 타이핑하신 질문 — 오직 그것만 — 이 주제를 고르기 위해 모델 제공자에게 갑니다. " +
        "어떤 문서도, 추출된 어떤 항목도, 세대 기록도 결코 가지 않습니다."
      ]
    }
  };

  var blockOriginals = new WeakMap();   // 요소 → 떼어 둔 영어 자식 노드 배열
  var touchedBlock = [];

  /** 영어가 우리가 번역한 그 영어일 때만 바꿔치기한다.
   *
   *  사전 항목은 영어가 바뀌면 조회가 빗나가 저절로 영어로 남는다. 이 구역은 키가
   *  속성이라 그 안전장치가 없으므로, 대조를 손으로 한다. 문장부호나 줄바꿈이 아니라
   *  글자만 본다 — <em>·<code> 가 끼어 있어 textContent 로는 태그가 사라지고, 원문의
   *  줄바꿈과 들여쓰기는 의미가 없기 때문이다. */
  function blockMatches(element, expected) {
    return normalize(element.textContent) === normalize(expected);
  }

  function applyBlock(element) {
    var key = element.getAttribute("data-i18n-block");
    var entry = BLOCKS[key];
    if (!entry || blockOriginals.has(element)) return;
    if (!blockMatches(element, entry.en)) {
      // 영어가 우리가 아는 영어가 아니다. 낡은 한국어를 보여 주는 것은 틀린 주장을
      // 보여 주는 것이므로, 번역을 포기하고 영어를 남긴다.
      if (window.console && window.console.warn) {
        window.console.warn(
          "[i18n] data-i18n-block=\"" + key + "\" 의 영어 원문이 바뀌었습니다. " +
          "낡은 한국어 대신 영어를 그대로 둡니다. i18n.js 의 BLOCKS 를 새 원문에 맞춰 " +
          "다시 쓰고 en 값도 함께 갱신하세요.");
      }
      return;
    }
    var parts = entry.ko;
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
      if (!m) continue;
      // 규칙이 걸렸어도 handler 가 null 을 돌리면 "나는 이 문장을 못 옮긴다"는 뜻이므로
      // 다음 규칙에게 넘긴다. 여기서 곧장 null 을 돌려주면, 넓은 규칙 하나가 자기보다
      // 뒤에 있는 좁은 규칙을 통째로 가려 버린다. 실제로 "We still need your
      // employer's letter:" 가 그렇게 막혔다 — 문서 이름 규칙이 콜론까지 삼켜 포기하고,
      // 뒤의 "<이름>:" 규칙이 시도조차 되지 않았다.
      var ko = RULES[i][1](m);
      if (ko !== null && ko !== undefined) return ko;
    }
    return null;
  }

  // ── DOM 적용 ────────────────────────────────────────────────────────────────
  // 기계 식별자가 사는 곳은 건드리지 않는다. 규칙 id·필드명·좌표·엔진 sha 는
  // 번역 대상이 아니라 데이터다.
  // .box-tag 는 더 이상 건너뛰지 않는다: 태그가 기계 식별자 대신 표의 평문 단어
  // (fieldWords)를 입게 되면서 번역 대상이 됐다. 기계 id 는 태그의 title 속성에
  // 남는데, 사전에 그 키가 없으므로 저절로 번역되지 않는다 — 데이터는 데이터로 남는다.
  var SKIP = "script, style, code, .mono, .formula, .schematic-text, #footer-meta";
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
