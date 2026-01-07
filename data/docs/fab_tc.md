# FAB TC

## TC란?
- 삼성 FAB 이라고 하면 기흥/화성/평택 반도체 라인을 말한다.
- FAB Line 에는 Memory / Foundry Line 으로 나뉜다.
- Memory Line : 12,13,15,16,17,U1,U2,U4,M1,P1,P2,P3,P4,PM,WP,TSV1,S5 등이 있다.
- Foundry Line : S1,S3,S4 등이 있다.
- S5는 평택에 있는 라인이다.
- TC 는 Tool Controler 의 약자로 Tool = Equipment 와 상위시스템 (MOS,FDC,RMS,YMS,EES 등) 과 메시지를 연결해주는 역할을 한다.
- 중간에서 메시지를 교환해주는 이유는 Tool = Equpiment = 설비 는 SECS/GEM 통신을 하고, 상위시스템은 Tivrv 통신을 하기에 통신 규약이 서로 맞지 않는다.

## TC2.5
- TC는 현재 TC1.0 / TC2.5 이렇게 2개로 운영중.
- TC1.0 은 200mm 라인에서 운영.
- TC2.5 는 300mm/400mm 라인에서 운영.
- TC1.0 은 .Net/Windows 기반이며, TC2.5 는 Java/Linux. 변경되는 이유는 .Net Framework 의 보안 update 종료로 인해 하드웨어 사양 및 운영중인 프로그램을 쉽게 바꿀수 없는 공장 특성상 오랜기간 운영이 가능한 Java/Linux 로 변경.
- TC 시스템은 TBL,MP(TDI),MPI 로 구성. TBL 은 TC의 전반적인 로직이며, MP(TDI)는 EES 와 통신하는 로직, MPI 는 설비 Interface 를 담당한다.
- Source 구성은 common.jar / tblstandardAction.jar / tbl.jar / action.jar 로 구성되며 tbl.jar 가 실행 파일이며, action.jar 가 tblstandardAction.jar 를 상속하며, tblstandardAction.jar 가 common.jar 를 상속하는 구성이다.
- TBL 은 AP1,AP2 로 나뉘어서 운영중에 있으며, 2개로 나눈 이유는 병렬 처리 및 장애 발생시에도 대처가 가능하도록 나뉘어져 있다. (ex: SET01 -> TBL01,TBL02 / SET02 -> TBL03,TBL04)
- 서버는 AP,MP 로 나뉘며 AP에는 TBL,MP(TDI) 가 있고 MP에는 MPI가 있다. 이렇게 구성되는 이유는 MP서버(MPI 가 들어가 있음)는 실제 설비와 Interface 하기에 update 를 하려면 연결을 끊어야한다. 이렇게 연결이 필요한 MPI 를 제외한 나머지는 update 가 자유롭도록 서버를 나누어서 구성.

## FAB 공정
- FAB TC 에서는 공정을 10개로 나누어서 개발한다.
- CVD, CMP, DIFF(SINGLE/BATCH), IMP, ETCH, METAL, WET(SINGLE/BATCH), ETC, METRO, PHOTO

## WORK
- TC 는 WORK 이라는 단위으로 LOT 을 진행
- 1개의 WORK에는 여러개의 CARRIER 가 들어갈 수 있고, CARRIER 에는 