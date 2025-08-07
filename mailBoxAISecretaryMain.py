import email
import zipfile
import io
import os
import json
import openai
from email import policy
from email.parser import BytesParser
import streamlit as st
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from azure.storage.blob import ContentSettings

load_dotenv()

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER")

openai.api_key = os.getenv('OPENAI_API_KEY')
openai.azure_endpoint = os.getenv('AZURE_ENDPOINT')
openai.api_type = os.getenv('OPENAI_API_TYPE')
openai.api_version = os.getenv('OPENAI_API_VERSION')

st.title("📬AI 메일함 관리 비서")
st.info("사번을 입력하여 AI를 활용한 메일함 관리를 시작해보세요.")

# 사번 체크 함수
def check_emp_id(emp_id):
    emp_info = {
        "82266328": "안녕하세요. 권혁우(DWP개발팀/hw41kwon@kt.com)님",
        "82222007": "안녕하세요. 테스터1(/test.grmail01@kt.com)님",
    }
    return emp_info.get(emp_id, None)

# 세션 상태에 인증 성공/실패 플래그 및 업로드 파일 기록
if "is_authenticated" not in st.session_state:
    st.session_state.is_authenticated = False
if "emp_name" not in st.session_state:
    st.session_state.emp_name = None
if "uploaded_initialInfo_file" not in st.session_state:
    st.session_state.uploaded_initialInfo_file = None

def parse_eml(eml_file):
    msg = BytesParser(policy=policy.default).parse(eml_file)
    subject = msg['subject'] if msg['subject'] else "(제목 없음)"
    sender = msg['from'] if msg['from'] else "(보낸이 없음)"
    date = msg['date'] if msg['date'] else "(날짜 없음)"

    # 본문 추출
    body = None
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                body = part.get_content()
                break
        if body is None:
            body = "(본문 없음)"
    else:
        body = msg.get_content()
    return {
        "subject": subject,
        "from": sender,
        "date": date
    }

def uploadUserData(emp_id, jsonData, uploadType):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_STORAGE_CONTAINER)
        if uploadType == "mailZip":
            blob_client = container_client.get_blob_client(f'{emp_id}.json')
            blob_client.upload_blob(json.dumps(jsonData, ensure_ascii=False), overwrite=True)
        elif uploadType == "mailboxInfo":
            blob_client = container_client.get_blob_client(f'{emp_id}_mailboxInfo.json')
            blob_client.upload_blob(json.dumps(jsonData, ensure_ascii=False), overwrite=True)
        elif uploadType == "mailFilterInfo":
            blob_client = container_client.get_blob_client(f'{emp_id}_mailFilterInfo.json')
        blob_client.upload_blob(json.dumps(jsonData, ensure_ascii=False), overwrite=True)
    
    except Exception as e:
        st.error(f"An error occurred: {e}")

def getFilteringMailBoxInfo(all_eml_json):
    # 초기 분류 메일함 추천 및 추천한 메일함 정보 저장
    response = openai.chat.completions.create(
        model="dev-gpt-4.1-mini",
        messages=[
            {"role": "system", "content": 
                """당신은 메일함 분류를 도와주는 AI 비서입니다.
                   \n사용자가 제공한 메일 데이터를 기반으로 메일함을 어떻게 분류할지 추천해주는 역할을 합니다.
                   \n*규칙1: 응답 데이터는 반드시 json 형태로 반환해야 합니다.
                   \n*규칙2: json 응답값에는 항상 3가지(mailBox, reason, filter) 데이터로 구성해야합니다.
                   \n    첫번째(Key: mailBox): 추천하는 메일함들 이름을 콤마&공백((예시)메일함1, 메일함2, ...) 구분으로 나열한 문자열
                   \n    두번째(Key: reason): 해당 메일함들을 추천하게된 상세 이유
                   \n    세번째(Key: filter): 발신자 주소 패턴 또는 메일 제목 패턴 추출
                   \n*규칙3: 세번째 json응답값(filter)도 json 형태로 구성해야합니다.
                   \n    filter를 구성할 데이터는 어떤 발신자 또는 메일 제목 패턴에 의해 어떤 메일함으로 분류해야하는지를 의미합니다.
                   \n    filter를 구성할 데이터: {"분류 인덱스 번호": {"발신자 정보 패턴 또는 메일 제목 패턴": "값", "메일함": "값"}}
                   \n    예시1) {"0": {"fromPattern": "권혁우(test@kt.com)", "mailBox": "개인 메일함"}", ...}
                   \n    예시2) {..., "1": {"subjectPattern": "회의", "mailBox": "회의 메일함"}", ..."""},
            {"role": "user", "content": f"{all_eml_json}"}
        ]
    )
    
    resultJson = json.loads(response.choices[0].message.content)
    
    ## 메일함 정보 저장하기
    uploadUserData(emp_id, {"mailBox" : resultJson['mailBox']}, "mailboxInfo")
    
    ## 메일함 분류 정보 저장하기
    uploadUserData(emp_id, {"mailFilter" : resultJson['filter']}, "mailFilterInfo")
    
    ## 분류 결과 표시해주기
    st.success(f"[메일함 추천]  \n{resultJson['mailBox']}")

    filterInfoStr = ""
    for filter_data in resultJson['filter'].items():
        filterInfoStr += f"{filter_data[1]}  \n"
    st.success(f"[메일 분류 추천]  \n{filterInfoStr}")
    st.success(f"[분석 내용]  \n{resultJson['reason']}")

def isExistUserMailData(emp_id):
    all_eml_json = {}
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_STORAGE_CONTAINER)
        blob_client = container_client.get_blob_client(f'{emp_id}_mailboxInfo.json')

        if blob_client.exists():
            st.success("""기존에 추천해드렸던 메일함과 분류 정보는 아래와 같습니다.
                        \n메일함 추천을 다시 받고싶으시다면 메일 데이터를 다시 업로드해주세요.""")
            try:
                #### 메일함 출력
                blob_client = container_client.get_blob_client(f'{emp_id}_mailboxInfo.json')
                # Blob에서 데이터 다운로드
                blob_data = blob_client.download_blob()
                json_content = blob_data.readall()
                # JSON 데이터 파싱
                mailbox_info = json.loads(json_content.decode('utf-8'))
                # 화면에 출력
                st.success(f"[메일함 추천]  \n{mailbox_info['mailBox']}")
                #### 분류 정보 출력
                blob_client = container_client.get_blob_client(f'{emp_id}_mailFilterInfo.json')
                # Blob에서 데이터 다운로드
                blob_data = blob_client.download_blob()
                json_content = blob_data.readall()
                # JSON 데이터 파싱
                mailFilter_info = json.loads(json_content.decode('utf-8'))
                # 화면에 출력
                filterInfoStr = ""
                for filter_data in mailFilter_info['mailFilter'].items():
                    filterInfoStr += f"{filter_data[1]}  \n"
                st.success(f"[메일 분류 추천]  \n{filterInfoStr}")
            except Exception as e:
                st.error(f"데이터를 읽어오는 중 오류가 발생했습니다: {str(e)}")
        else:
            st.success(f"메일 데이터를 제공해주시면 메일 관리 방안을 추천해드리겠습니다.")

        uploaded_initialInfo_file = st.file_uploader(
            "zip 파일을 업로드해주세요.",
            type=['zip'],
            key="file_uploader_key",
        )
        
        st.session_state.uploaded_initialInfo_file = uploaded_initialInfo_file  # 세션에 저장

        # 업로드 파일이 있을 때만 처리
        if st.session_state.uploaded_initialInfo_file is not None:
            up_file = st.session_state.uploaded_initialInfo_file
            if up_file.name.lower().endswith('.zip'):
                with zipfile.ZipFile(up_file) as z:
                    eml_files = [f for f in z.namelist() if f.lower().endswith('.eml')]
                    if not eml_files:
                        st.warning("압축파일에 eml 파일이 없습니다.")
                    else:
                        for idx, eml_name in enumerate(eml_files):
                            with z.open(eml_name) as eml_file:
                                eml_bytes = io.BytesIO(eml_file.read())
                                eml_bytes.seek(0)
                                eml_json = parse_eml(eml_bytes)
                                all_eml_json[f"{idx}"] = eml_json

                        #### 스토리지 업로드
                        uploadUserData(emp_id, all_eml_json, "mailZip")

                        #### gpt-4.1-mini 호출 (메일 데이터 정보로 메일 분류 추천)
                        getFilteringMailBoxInfo(all_eml_json)

                        #### 결과 표시
                        # st.subheader("EML 파싱 데이터(JSON 리스트)")
                        # st.json(all_eml_json)
            else:
                st.error("zip 파일만 지원합니다.")
        else:
            st.info("zip 파일을 업로드 해주세요.")

    except Exception as e:
        st.error(f"An error occurred: {e}")
    return False


# ---------- 인증 폼 ----------
with st.form("emp_form"):
    emp_id = st.text_input(
        "",
        max_chars=20,
        placeholder="사번을 입력하세요.",
        key="emp_id_key",
        label_visibility="collapsed"
    )
    submitted = st.form_submit_button("확인", use_container_width=True)

if submitted:
    emp_name = check_emp_id(emp_id)
    if emp_name:
        st.session_state.is_authenticated = True
        st.session_state.emp_name = emp_name
    else:
        st.session_state.is_authenticated = False
        st.session_state.emp_name = None
        st.error("유효한 사번을 입력해주세요.")

# ---------- 인증 성공 시 파일 업로더 노출 ----------
if st.session_state.is_authenticated:
    st.success(st.session_state.emp_name)
    isExistUserMailData(emp_id)
    


# st.button("함수 실행eeeeeeeeeeeeeeeeeee")

# def my_function():
#     st.write("함수가 실행되었습니다!")
#     # 여기에 원하는 동작을 작성하세요

# # 버튼 생성 및 함수 실행
# if st.button("함수 실행"):
#     my_function()