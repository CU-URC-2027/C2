// Discovery is parsed separately and never calls C2Guard::accept or updates a lease.
#pragma once
#include <stddef.h>
#include <string.h>
#include <stdint.h>

inline bool c2discoveryQuery(const char* data, size_t size, char (&nonce)[17]) {
  if (size==25 && data[24]=='\n') --size;
  if (size!=24 || memcmp(data,"C2DISC1,",8)) return false;
  for (size_t i=8;i<24;++i)
    if (!((data[i]>='0' && data[i]<='9') || (data[i]>='a' && data[i]<='f'))) return false;
  memcpy(nonce,data+8,16); nonce[16]=0; return true;
}

inline bool c2urgentReply(bool wasEnabled, bool wasStopped, uint32_t wasEpoch,
                          bool enabled, bool stopped, uint32_t epoch, const char* op) {
  return wasEnabled!=enabled || wasStopped!=stopped || wasEpoch!=epoch || !strcmp(op,"HELLO");
}
