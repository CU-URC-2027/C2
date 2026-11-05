// Portable scheduling and state formatting; also exercised by native tests.
#pragma once
#include "C2Guard.h"
#include <stdio.h>

struct C2IoSchedule {
  static const uint32_t statePeriodMs=100, detailPeriodMs=1000, rxBudgetMs=120;
  static const unsigned rxPacketLimit=8;
  uint32_t lastState=0, lastDetail=0;
  bool sentState=false, sentDetail=false;
  bool receiveMore(unsigned count, uint32_t started, uint32_t now) const {
    return count<rxPacketLimit && uint32_t(now-started)<rxBudgetMs;
  }
  bool stateDue(uint32_t now) const {
    return !sentState || uint32_t(now-lastState)>=statePeriodMs;
  }
  bool detailDue(uint32_t now, bool urgent, bool enabled, bool rxDrained) const {
    // Large modem transfers wait until outputs are disabled and RX is drained.
    return !urgent && !enabled && rxDrained &&
      (!sentDetail || uint32_t(now-lastDetail)>=detailPeriodMs);
  }
};

inline int c2formatState(char* out, size_t capacity, const C2Guard& guard,
                        uint32_t stateId, const char* encoders,
                        const char* deviceId, const char* bootId, const char* extra="") {
  int n=snprintf(out,capacity,
    "{\"v\":1,\"type\":\"state\",\"fw\":\"c2-guard-v1\",\"session\":\"%s\","
    "\"seq\":%lu,\"epoch\":%lu,\"state_id\":%lu,\"enabled\":%s,\"stopped\":%s,"
    "\"throttle\":%d,\"steering\":%d,\"encoders\":[%s],\"reason\":\"%s\","
    "\"watchdog_ms\":250,\"max_pwm\":255,\"device_id\":\"%s\",\"boot_id\":\"%s\"%s}",
    guard.session,(unsigned long)guard.seq,(unsigned long)guard.epoch,(unsigned long)stateId,
    guard.enabled?"true":"false",guard.stopped?"true":"false",guard.throttle,guard.steering,
    encoders,guard.reason,deviceId,bootId,extra);
  return n>0 && (size_t)n<capacity ? n : 0; // Never transmit truncated JSON.
}
