# -*- coding: utf-8 -*-
"""
솔라나 자동 매매 봇 - 자동 복구 시스템
API 연결 끊김, 데이터 수집 실패 등을 자동으로 복구
"""

import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class AutoRecovery:
    """자동 복구 클래스"""
    
    def __init__(self, telegram_sender=None):
        self.telegram_sender = telegram_sender
        self.recovery_attempts = 0
        self.last_recovery_time = None
        
        logger.info("🔄 자동 복구 시스템 초기화")
    
    def retry_api_connection(self, client, max_retries=3):
        """API 연결 재시도"""
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 API 재연결 시도 ({attempt + 1}/{max_retries})")
                
                # API 핑 테스트
                ping = client.futures_ping()
                if ping:
                    logger.info("✅ API 재연결 성공")
                    return True
            
            except Exception as e:
                logger.warning(f"⚠️  API 재연결 실패 ({attempt + 1}/{max_retries}): {str(e)}")
                
                if attempt < max_retries - 1:
                    # 다음 시도 전 대기 (지수 백오프)
                    wait_time = 5 * (2 ** attempt)  # 5초, 10초, 20초
                    logger.info(f"⏳ {wait_time}초 후 재시도...")
                    time.sleep(wait_time)
        
        logger.error("❌ API 재연결 실패 (모든 시도 완료)")
        return False
    
    def retry_data_fetch(self, fetch_func, max_retries=5):
        """데이터 수집 재시도"""
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 데이터 수집 재시도 ({attempt + 1}/{max_retries})")
                
                result = fetch_func()
                if result is not None:
                    logger.info("✅ 데이터 수집 성공")
                    return result
            
            except Exception as e:
                logger.warning(f"⚠️  데이터 수집 실패 ({attempt + 1}/{max_retries}): {str(e)}")
                
                if attempt < max_retries - 1:
                    wait_time = 3 * (2 ** attempt)  # 3초, 6초, 12초...
                    logger.info(f"⏳ {wait_time}초 후 재시도...")
                    time.sleep(wait_time)
        
        logger.error("❌ 데이터 수집 실패 (모든 시도 완료)")
        return None
    
    def recover_from_error(self, error_msg, error_type='일반'):
        """오류로부터 복구"""
        self.recovery_attempts += 1
        self.last_recovery_time = datetime.now()
        
        logger.info(f"🔄 복구 시작: [{error_type}] {error_msg}")
        
        recovery_msg = f"🔄 <b>자동 복구 시도 중</b>\n\n"
        recovery_msg += f"오류: {error_type}\n"
        recovery_msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        if self.telegram_sender:
            try:
                self.telegram_sender(recovery_msg)
            except:
                pass
    
    def notify_recovery_success(self):
        """복구 성공 알림"""
        logger.info("✅ 자동 복구 성공")
        
        success_msg = f"✅ <b>자동 복구 성공</b>\n\n"
        success_msg += f"봇이 자동으로 복구되었습니다.\n"
        success_msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        if self.telegram_sender:
            try:
                self.telegram_sender(success_msg)
            except:
                pass
    
    def notify_recovery_failure(self, error_msg):
        """복구 실패 알림"""
        logger.error(f"❌ 자동 복구 실패: {error_msg}")
        
        failure_msg = f"❌ <b>자동 복구 실패</b>\n\n"
        failure_msg += f"오류: {error_msg}\n"
        failure_msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        failure_msg += f"⚠️  <b>수동 개입이 필요합니다!</b>"
        
        if self.telegram_sender:
            try:
                self.telegram_sender(failure_msg)
            except:
                pass
    
    def get_recovery_status(self):
        """복구 상태 조회"""
        status = f"\n복구 시도: {self.recovery_attempts}회\n"
        if self.last_recovery_time:
            status += f"마지막 복구: {self.last_recovery_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        return status

# 테스트
if __name__ == '__main__':
    recovery = AutoRecovery()
    logger.info(recovery.get_recovery_status())
