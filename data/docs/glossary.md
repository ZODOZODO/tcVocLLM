# 추가 자료 및 정보

## AMHS란?
- AMHS? Automated Material Handling System (자동화 자재 이송 시스템)
- 반도체 제조 라인에서 웨이퍼(FOUP)나 부품을 공정 장비나 창고로 자동으로 이송, 저장, 관리하는 전체 시스템을 말합니다.
- 먼지와 진동을 최소화하며 효율적인 물류 흐름을 만듭니다.
- 추가적으로 AUTO/MANUAL 로 통제

## APC란?
- APC? Advanced Process Control
- 반도체 제조 공정에서 변수를 실시간으로 모니터링하고 제어하여 품질을 유지하거나 향상시키는데 사용하는 기술.
- Wafer를 가공하는 Recipe의 특정 값을 변경하는 경우가 많음. 이에 PROCESSJOBCREATE 에 보통 넣어서 사용.
- 이외에는 MES 에서 메시지를 따로 구성하여 WAFER 가 동작전 TC를 통해 TOOL로 명령을 내림.

## PROCESSJOB
- ProcessJob = ‘공정 실행 단위’(레시피/파라미터 중심)
- ProcessJob은 장비가 수행할 공정 실행의 내용을 정의.
- 특정 재료(Material)에 대해 어떤 레시피(Recipe)를 어떤 파라미터로 수행할지, 그리고 공정 수행에 필요한 각종 조건/제약을 포함.
- PJ의 역할은 공정 자체의 재현성/추적성 확보: “이 웨이퍼들은 이 레시피/조건으로 처리되었다”를 명확히 남기며, 실행 단위로서의 상태/이벤트 제공: 진행/완료/중단/에러를 PJ 수준에서 관리 가능.

## ControlJob
- ControlJob은 하나 이상의 ProcessJob을 묶어서 장비가 실제로 “운영”할 때 필요한 스케줄링/자원할당/물류(Load/Unload)/진행 제어를 담당하는 상위 오브젝트.
- 특히 300mm 자동화(FOUP/EFEM/AMHS) 환경에서는 “캐리어를 로드해서, 웨이퍼를 이 경로로 흘려서, 이 순서로 처리하고, 끝나면 언로드”까지가 운영의 핵심이라 CJ가 매우 중요.

## SECS/GEM
- 반도체 장비(EQP)와 공장 시스템(Host/MES)이 서로 같은 규칙으로 대화하게 해주는 국제 표준 인터페이스.
- SECS = “대화의 문법/문장 형식” / GEM = “무슨 대화를 해야 하는지(대화 주제/업무 규칙)”.
- SECS-I + HSMS: 통신 방식.
- SECS-I: 옛날 방식. 보통 RS-232(직렬 통신) 기반. 느리고 거리/구성이 제한적.
- HSMS: 요즘 방식. TCP/IP(Ethernet) 기반. 빠르고 네트워크 친화적.
- HSMS = TCP 위에서 동작하는 SECS 전용 규칙(상위 계층 프로토콜)
- 데이터 단위의 차이: TCP는 “스트림”, HSMS는 “메시지”
- SECS-II: “대화 내용(메시지 구조/타입)”
- GEM: “업무 규칙(장비 자동화 기능의 표준 세트)”

## Tibrv
- TIBCO Rendezvous는 분산 애플리케이션 간 메시지 통신을 위한 고성능 메시징 미들웨어.
- 주로 publish/subscribe(주제 기반 브로드캐스트) 방식으로 실시간 데이터를 배포하는 데 강점.
- 일반적으로 멀티캐스트 기반으로 다수 수신자에게 낮은 지연으로 배포.
- Daemon 기반 아키텍처로 애플리케이션이 네트워크를 직접 다루기보다, 로컬/원격의 Rendezvous daemon(rvd) 과 연결해 송수신을 수행하는 구성이 일반적.
- transport 파라미터: network, service, daemon
- service : transport가 네트워크 통신을 할 때 사용할 ‘서비스(포트/서비스명)’
- daemon : 애플리케이션이 연결할 Rendezvous daemon(rvd)의 위치 (ex : tcp:7500 (로컬 머신의 rvd에 TCP 7500 포트로 연결) 또는 tcp:host:port)
- network : transport가 사용할 네트워크(인터페이스/세그먼트/멀티캐스트 관련 설정) 를 지정하는 파라미터.
