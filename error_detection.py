# -*- coding: utf-8 -*-
"""
솔라나 자동 매매 봇 - 긴급 오류 감지 시스템
심각한 문제 발생 시 즉시 텔레그램 알림
"""

import os
import psutil
import time
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ErrorDetector:
    """긴급 오류 감지 클래스"""
    
    def __init__(self, telegram_sender=None):
        self.telegram_sender = telegram_sender
        self.error_log = []
        self.last_check = datetime.now()
        
        # 경고 임계값
        self.CPU_THRESHOLD = 80  # CPU 80% 이상
        self.MEMORY_THRESHOLD = 85  # 메모리 85% 이상
        self.DISK_THRESHOLD = 90  # 디스크 90% 이상
        
        logger.info("🔴 긴급 오류 감지 시스템 초기화")
    
    def check_system_health(self):
        """시스템 건강 상태 체크"""
        issues = []
        
        # CPU 사용률 체크
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > self.CPU_THRESHOLD:
            issues.append(f"🔴 CPU 과부하: {cpu_percent}%")
        
        # 메모리 사용률 체크
        memory = psutil.virtual_memory()
        if memory.percent > self.MEMORY_THRESHOLD:
            issues.append(f"🔴 메모리 부족: {memory.percent}% (사용 가능: {memory.available / (1024**3):.1f}GB)")
        
        # 디스크 사용률 체크
        disk = psutil.disk_usage('/')
        if disk.percent > self.DISK_THRESHOLD:
            issues.append(f"🔴 디스크 부족: {disk.percent}% (사용 가능: {disk.free / (1024**3):.1f}GB)")
        
        return issues
    
    def check_api_connection(self, client):
        """API 연결 상태 체크"""
        try:
            # Binance API 핑 테스트
            ping = client.futures_ping()
            if ping:
                return True, None
        except Exception as e:
            error_msg = f"🔴 Binance API 연결 끊김: {str(e)}"
            return False, error_msg
        
        return False, "🔴 Binance API 상태 불명"
    
    def check_process_health(self, process_name='solana_trading_bot_final.py'):
        """프로세스 상태 체크"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if process_name in ' '.join(proc.info['cmdline'] or []):
                    return True, None
            
            return False, f"🔴 프로세스 실행 중지됨: {process_name}"
        except Exception as e:
            return None, f"⚠️  프로세스 체크 오류: {str(e)}"
    
    def detect_critical_errors(self, client=None):
        """긴급 오류 감지"""
        critical_errors = []
        
        # 1. 시스템 건강 체크
        system_issues = self.check_system_health()
        critical_errors.extend(system_issues)
        
        # 2. API 연결 체크
        if client:
            api_ok, api_error = self.check_api_connection(client)
            if not api_ok:
                critical_errors.append(api_error)
        
        # 3. 프로세스 체크
        proc_ok, proc_error = self.check_process_health()
        if proc_ok is False:
            critical_errors.append(proc_error)
        
        return critical_errors
    
    def send_critical_alert(self, errors):
        """긴급 알림 전송"""
        if not errors or not self.telegram_sender:
            return
        
        alert_msg = f"🚨 <b>긴급 오류 감지!</b>\n\n"
        alert_msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        for error in errors:
            alert_msg += f"{error}\n"
        
        alert_msg += f"\n\n⚠️  <b>즉시 확인이 필요합니다!</b>"
        
        try:
            self.telegram_sender(alert_msg)
            logger.error(f"긴급 알림 전송됨: {len(errors)}개 오류")
        except Exception as e:
            logger.error(f"긴급 알림 전송 실패: {str(e)}")
    
    def log_error(self, error_msg, error_type='일반'):
        """오류 기록"""
        error_record = {
            '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '유형': error_type,
            '메시지': error_msg
        }
        self.error_log.append(error_record)
        logger.error(f"[{error_type}] {error_msg}")
    
    def get_error_summary(self):
        """오류 요약"""
        if not self.error_log:
            return "오류 없음"
        
        summary = f"\n최근 오류 {len(self.error_log)}개:\n"
        for i, error in enumerate(self.error_log[-10:], 1):  # 최근 10개
            summary += f"{i}. [{error['유형']}] {error['시간']}: {error['메시지']}\n"
        
        return summary

# 테스트
if __name__ == '__main__':
    detector = ErrorDetector()
    
    # 시스템 상태 체크
    errors = detector.detect_critical_errors()
    if errors:
        print("발견된 문제:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("✅ 시스템 정상")
