# 솔라나(SOL/USDT) 자동 매매 봇

## 📋 프로젝트 개요
- **전략**: SMC (Smart Money Concept)
- **종목**: SOL/USDT (솔라나 선물)
- **타임프레임**: 1시간봉
- **거래소**: Binance 선물 (Futures)
- **서버**: AWS Ubuntu 24.04.4

---

## ⚙️ 전략 파라미터
- **PIVOT_LOOKBACK**: 5
- **RR_RATIO**: 8.0
- **LEVERAGE**: 5배
- **초기 자본**: $600
- **수수료**: 0.07%

---

## 🗂️ 파일 구조
~/solana_bot_new/
├── solana_bot_config.py                      # 바이낸스 API 키 + 전략 설정
├── telegram_config.py                         # 텔레그램 봇 토큰 + 채팅 ID
├── trading_journal.py                         # 매매일지 자동 생성 (한글)
├── error_detection.py                         # 긴급 오류 감지 시스템
├── auto_recovery.py                           # 자동 복구 시스템
├── solana_trading_bot_with_auto_recovery.py   # 메인 봇 파일 (현재 실행 중)
├── requirements.txt                           # 필요 패키지 목록
├── sol_trading_bot.log                        # 봇 로그 파일
├── trading_journals/                          # 매매일지 저장 폴더
└── .github/workflows/deploy.yml              # GitHub Actions 자동 배포

---

## 🖥️ AWS 서버 정보
- **IP**: 13.63.253.13
- **OS**: Ubuntu 24.04.4
- **유저**: ubuntu
- **봇 디렉토리**: ~/solana_bot_new
- **가상환경**: ~/solana_bot_env

---

## 📱 텔레그램 설정
- **봇 토큰**: telegram_config.py 참조
- **채팅 ID**: telegram_config.py 참조
- **알림 종류**:
  - ✅ 롱/숏 진입
  - ✅ 익절/손절
  - 🔴 긴급 오류
  - 🔄 자동 복구 성공/실패
  - ⛔ 봇 종료

---

## 🚀 GitHub Actions 자동 배포
- **저장소**: https://github.com/kimjiho2-art/solana-trading-bot
- **배포 방식**: main 브랜치에 push 시 자동 배포
- **GitHub Secrets**:
  - AWS_HOST: 13.63.253.13
  - AWS_USERNAME: ubuntu
  - AWS_SSH_KEY: ~/.ssh/github_actions_key

---

## ✅ 구축된 기능
- **Phase 1**: 매매일지 자동 생성 (한글)
- **Phase 2**: 매매 분석 (거래 쌓이면 활성화 예정)
- **Phase 3**: 긴급 오류 감지 시스템
- **Phase 4**: 자동 복구 시스템
- **Phase 5**: GitHub Actions 자동 배포

---

## 🔧 봇 관리 명령어

### 봇 상태 확인:
```bash
screen -ls
```

### 봇 로그 확인 (실시간):
```bash
tail -f ~/solana_bot_new/sol_trading_bot.log
```

### 봇 화면 접속:
```bash
screen -r solana_trading_final
```
(나가기: Ctrl + A → D)

### 봇 중단:
```bash
screen -X -S solana_trading_final quit
```

### 봇 재시작:
```bash
screen -S solana_trading_final -d -m bash -c "cd ~/solana_bot_new && source ~/solana_bot_env/bin/activate && python3 solana_trading_bot_with_auto_recovery.py"
```

### 가상환경 활성화:
```bash
source ~/solana_bot_env/bin/activate
```

---

## 🔄 코드 수정 워크플로우

1. 텔레그램에서 오류 메시지 수신
2. Claude 앱에 오류 내용 전달
   - **반드시 GitHub 주소 함께 전달**:
   - https://github.com/kimjiho2-art/solana-trading-bot
3. Claude가 수정 코드 제공
4. AWS 터미널에서 수정 코드 붙여넣기
5. 아래 명령어 실행:
```bash
cd ~/solana_bot_new && git add . && git commit -m "오류 수정" && git push origin main
```
6. GitHub Actions 자동 배포
7. 텔레그램에서 "배포 완료" 확인

---

## ⚠️ 주의사항
- API 키는 solana_bot_config.py에 저장됨 (GitHub에 업로드 X)
- 텔레그램 토큰은 telegram_config.py에 저장됨 (GitHub에 업로드 X)
- 레버리지 5배 운영 중 (변경 시 solana_bot_config.py 수정)
- 거래 발생 시 trading_journals/ 폴더에 자동 저장

---

## 📊 백테스팅 결과
- **BTC**: 200% (75회)
- **BNB**: 45% (86회)
- **SOL**: 900% (79회) ← 현재 운영 중

---

## 🆘 새 채팅에서 Claude에게 전달할 내용
GitHub 주소: https://github.com/kimjiho2-art/solana-trading-bot
README를 읽고 아래 오류를 수정해줘:
[오류 메시지 붙여넣기]
