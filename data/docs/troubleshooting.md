# 자주 발생하는 장애

## TOOL_CONDITION_REPLY 진행시 FAIL 발생
- S1F3 을 설비로 보내고, S1F4 를 받고 PORT STATE IDLE 을 확인하여 비어있는 PORT 가 없을 경우 FAIL 발생
- MAXLOTCOUNT 가 모두 찼을 경우

## MES 에서 보내준 SLOT 정보와 설비에서 보내준 SLOT 정보 미일치
- CARRIERID_READ_REPLY 에서 보내준 SLOT 의 정보와 S6F11 로 올라온 설비의 SLOT 정보가 미일치한 경우 FAIL

## PROCESSJOBCREATE 진행 FAIL
- S16F11 or S16F15 (PROCESSJOBCREATE) 를 보내고 S16F12 or S16F16 이 FAIL 로 오는 경우
- PROCESSJOB 이 잘 못 만들어졌을 가능성 (자리수)
- RECIPEID (PPID) 가 잘 못 들어갔을 가능성
- APC 정보 미일치

## WORK_COMPLETED 진행 FAIL
- TKIN 시 저장한 Wafer 의 수와 실제 설비에서 진행한 Wafer 의 Processed Count 가 미일치
- DATACOLL 이 WORK_COMPLETED 보다 나중에 진행

## CARRIER_UNLOAD_COMPLETED 미발생
- UNLOAD_REQUEST 진행 후 WORK 이 삭제되어 미발생

