# -*- coding: utf-8 -*-
"""
솔라나 자동 매매 봇 - 매매일지 자동 생성
한글 완벽 지원
"""

import json
import os
from datetime import datetime
import pandas as pd

class TradingJournal:
    """매매일지 관리 클래스"""
    
    def __init__(self, journal_dir='trading_journals'):
        self.journal_dir = journal_dir
        
        # 폴더 생성
        if not os.path.exists(journal_dir):
            os.makedirs(journal_dir)
        
        self.daily_file = None
        self.trades = []
    
    def log_trade(self, trade_type, entry_price, exit_price, stop_loss, take_profit, pnl, duration):
        """거래 기록"""
        trade = {
            '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '거래유형': '롱' if trade_type == 'LONG' else '숏',
            '진입가': round(entry_price, 2),
            '손절가': round(stop_loss, 2),
            '익절가': round(take_profit, 2),
            '청산가': round(exit_price, 2),
            '손익(달러)': round(pnl, 2),
            '손익률': round((pnl / (entry_price * 1)) * 100, 2),
            '거래시간': str(duration)
        }
        
        self.trades.append(trade)
        self._save_daily_journal()
    
    def _save_daily_journal(self):
        """일일 매매일지 저장"""
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{self.journal_dir}/journal_{today}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.trades, f, ensure_ascii=False, indent=2)
    
    def generate_daily_report(self):
        """일일 리포트 생성"""
        if not self.trades:
            return "오늘 거래 없음"
        
        df = pd.DataFrame(self.trades)
        
        총거래수 = len(df)
        총수익 = df['손익(달러)'].sum()
        평균손익 = df['손익(달러)'].mean()
        
        롱거래 = len(df[df['거래유형'] == '롱'])
        숏거래 = len(df[df['거래유형'] == '숏'])
        
        롱수익 = df[df['거래유형'] == '롱']['손익(달러)'].sum()
        숏수익 = df[df['거래유형'] == '숏']['손익(달러)'].sum()
        
        보유 = len(df[df['손익(달러)'] > 0])
        손절 = len(df[df['손익(달러)'] < 0])
        승률 = (보유 / 총거래수 * 100) if 총거래수 > 0 else 0
        
        report = f"""
═══════════════════════════════════════════
📊 솔라나 매매일지 - {datetime.now().strftime('%Y년 %m월 %d일')}
═══════════════════════════════════════════

📈 주요 지표:
  • 총 거래수: {총거래수}회
  • 총 수익: ${총수익:.2f}
  • 평균 거래당: ${평균손익:.2f}
  • 승률: {승률:.1f}%

🎯 거래 분석:
  • 롱 거래: {롱거래}회 (수익: ${롱수익:.2f})
  • 숏 거래: {숏거래}회 (수익: ${숏수익:.2f})
  • 익절: {보유}회 ✅
  • 손절: {손절}회 ❌

═══════════════════════════════════════════
"""
        return report
    
    def export_to_csv(self):
        """CSV로 내보내기"""
        if not self.trades:
            return None
        
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{self.journal_dir}/journal_{today}.csv"
        
        df = pd.DataFrame(self.trades)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        
        return filename

# 테스트
if __name__ == '__main__':
    journal = TradingJournal()
    
    # 테스트 거래 기록
    from datetime import timedelta
    journal.log_trade(
        trade_type='LONG',
        entry_price=142.50,
        exit_price=186.20,
        stop_loss=142.10,
        take_profit=186.20,
        pnl=924.13,
        duration=timedelta(hours=4)
    )
    
    print(journal.generate_daily_report())
    print(f"✅ 매매일지 저장됨: {journal.journal_dir}")
