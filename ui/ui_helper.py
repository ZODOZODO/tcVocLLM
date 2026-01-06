import httpx
import streamlit as st
import streamlit.components.v1 as components


def get_http_client(timeout: float = 240) -> httpx.Client:
    """
    Streamlit session_state에 httpx.Client를 1회 생성해 재사용합니다.
    - 매 요청마다 client를 만들면 오버헤드가 커지고, 연결 재사용도 안 됩니다.
    - timeout은 호출 시점의 값을 우선 적용하도록 조정합니다.
    """
    if "http_client" not in st.session_state:
        st.session_state.http_client = httpx.Client(timeout=timeout)
        st.session_state.http_client_timeout = timeout
        return st.session_state.http_client

    # timeout이 변경되면 재생성(기존 Client의 timeout 속성 변경은 버전/타입에 따라 불안정할 수 있음)
    prev = st.session_state.get("http_client_timeout", None)
    if prev != timeout:
        try:
            st.session_state.http_client.close()
        except Exception:
            pass
        st.session_state.http_client = httpx.Client(timeout=timeout)
        st.session_state.http_client_timeout = timeout

    return st.session_state.http_client


def decode_bytes_best_effort(raw: bytes) -> str:
    """
    로그/문서 파일 bytes를 최대한 안전하게 문자열로 디코딩합니다.
    - 현장 문서/로그 고려: utf-8, utf-8-sig, cp949 순으로 시도
    - 전부 실패하면 errors="ignore"로 강제 디코딩
    """
    if raw is None:
        return ""

    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode(errors="ignore")


def scroll_to_anchor(anchor_id: str) -> None:
    """
    rerun 이후에도 특정 위치(anchor)로 스크롤시키기 위한 helper.
    - Streamlit은 위젯 변경 시 rerun되며 스크롤이 흔들릴 수 있어 UX 완화용으로 사용합니다.
    - logs_tab 등에서 <div id="..."></div> 앵커를 먼저 렌더링한 뒤 호출해야 합니다.
    """
    safe_id = (anchor_id or "").replace('"', "").replace("'", "")
    components.html(
        f"""
        <script>
          (function() {{
            const doc = window.parent.document;
            const el = doc.getElementById("{safe_id}");
            if (el) {{
              el.scrollIntoView({{ behavior: "instant", block: "start" }});
            }}
          }})();
        </script>
        """,
        height=0,
    )


def scroll_to_bottom() -> None:
    """
    페이지/메인 영역을 가능한 범위에서 맨 아래로 스크롤합니다.
    - VOC 채팅에서 '최신 답변이 보이게' 하는 용도로도 사용 가능
    - Streamlit DOM 구조 변경에 대비해 다중 fallback을 사용합니다.
    """
    components.html(
        """
        <script>
          (function () {
            const doc = window.parent.document;

            // 1) main 영역 스크롤(fallback)
            const main = doc.querySelector('section.main');
            if (main) main.scrollTo(0, main.scrollHeight);

            // 2) overflow 영역 후보들 중 마지막 요소를 스크롤
            const boxes = doc.querySelectorAll(
              'div[data-testid="stVerticalBlock"] div[style*="overflow"], div[style*="overflow: auto"], div[style*="overflow:auto"]'
            );
            if (boxes && boxes.length > 0) {
              const el = boxes[boxes.length - 1];
              el.scrollTop = el.scrollHeight;
            }

            // 3) 최후 fallback: 페이지 전체
            window.parent.scrollTo(0, doc.body.scrollHeight);
          })();
        </script>
        """,
        height=0,
    )


def ui_lock(message: str = "응답 생성 중입니다. 잠시만 기다려 주세요.") -> None:
    """
    브라우저 DOM에서 입력/버튼을 강제로 잠금(2차 잠금).
    - Streamlit 위젯 disabled가 즉시 반영되지 않는 케이스 대비
    - overlay로 클릭/입력을 차단합니다.
    """
    msg = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f"""
        <div class="tc-overlay">
          <div class="tc-overlay-card">{msg}</div>
        </div>
        <style>
          .tc-overlay {{
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.35);
            z-index: 2147483647;
            pointer-events: all;
          }}
          .tc-overlay-card {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(255, 255, 255, 0.95);
            color: #111;
            padding: 16px 20px;
            border-radius: 12px;
            font-weight: 700;
            box-shadow: 0 8px 30px rgba(0,0,0,0.25);
          }}
        </style>
        <script>
          (function() {{
            const doc = window.parent.document;

            // 입력/버튼 잠금(기존 상태 저장)
            const els = doc.querySelectorAll('input, textarea, button');
            els.forEach(el => {{
              if (!el.dataset.tcLock) {{
                el.dataset.tcLock = "1";
                el.dataset.tcPrevDisabled = el.disabled ? "1" : "0";
              }}
              el.disabled = true;
            }});

            // 포커스 제거
            if (doc.activeElement) doc.activeElement.blur();
          }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


def ui_unlock() -> None:
    """
    ui_lock으로 잠갔던 요소만 원복합니다.
    """
    st.markdown(
        """
        <script>
          (function() {
            const doc = window.parent.document;
            const locked = doc.querySelectorAll('[data-tc-lock="1"]');
            locked.forEach(el => {
              const prev = el.dataset.tcPrevDisabled;
              if (prev === "0") el.disabled = false;
              delete el.dataset.tcLock;
              delete el.dataset.tcPrevDisabled;
            });
          })();
        </script>
        """,
        unsafe_allow_html=True,
    )
