#include "../mini_rover_c2/C2Guard.h"
#include "../mini_rover_c2/C2Discovery.h"
#include "../mini_rover_c2/C2Telemetry.h"
#include <cassert>
#include <cstdio>
#include <string>

bool parse(const std::string& s) { C2Packet p; return c2parse(s.data(),s.size(),p); }
C2Packet command(const char* op, uint32_t seq, uint32_t epoch, int t=0, int s=0) {
  char text[128];
  snprintf(text,sizeof(text),"C2V1,0123456789abcdef,%lu,%lu,%s,%d,%d\n",(unsigned long)seq,(unsigned long)epoch,op,t,s);
  C2Packet p; assert(c2parse(text,strlen(text),p)); return p;
}

// Synthetic modem calls: bounded receive batches, 75-80 ms full sends, shorter
// compact sends and intermittent receive delays. Costs are assumptions, not a
// measured prediction for the board. Exercise the actual guard and scheduler.
uint32_t timingScenario(bool compact, uint32_t compactSendMs=35) {
  C2Guard guard;
  guard.accept(command("HELLO",1,0),0);
  guard.accept(command("ARM",2,guard.epoch),1);
  C2IoSchedule io;
  uint32_t now=1, next=0, seq=2, ackSentAt=0, previousAckAt=0, maxAge=0, reads=0;
  while (now<10000) {
    now+=6; // Synchronous Wi-Fi status/loop overhead.
    uint32_t started=now;
    unsigned count=0;
    bool drained=false;
    while (compact ? io.receiveMore(count,started,now) : count<4) {
      if (next>now) { now+=5; drained=true; break; }
      uint32_t sentAt=next; next+=50;
      now+=25+(++reads%11==0 ? 35 : 0);
      assert(guard.accept(command("DRIVE",++seq,guard.epoch,32),now));
      ackSentAt=sentAt;
      ++count;
    }
    guard.tick(now); assert(guard.enabled);
    if (!compact || io.stateDue(now)) {
      bool detail=io.detailDue(now,false,guard.enabled,drained);
      io.lastState=now; io.sentState=true;
      if (detail) { io.lastDetail=now; io.sentDetail=true; }
      now+=!compact || detail ? 80 : compactSendMs;
      // Before this reply arrives, the host still holds the PREVIOUS ACK.
      if (now-previousAckAt>maxAge) maxAge=now-previousAckAt;
      previousAckAt=ackSentAt;
    }
    // Upper bound until the next reply; the PC samples this at ~50 ms intervals.
    uint32_t age=now-previousAckAt;
    if (age>maxAge) maxAge=age;
    guard.tick(now); assert(guard.enabled);
  }
  return maxAge;
}

int main() {
  C2IoSchedule io;
  assert(io.receiveMore(7,100,219));
  assert(!io.receiveMore(8,100,101));
  assert(!io.receiveMore(1,100,220));
  assert(io.stateDue(0) && !io.detailDue(0,true,false,true));
  assert(!io.detailDue(0,false,true,true));
  assert(!io.detailDue(0,false,false,false));
  assert(io.detailDue(0,false,false,true));
  io.sentState=io.sentDetail=true; io.lastState=io.lastDetail=0xfffffff0U;
  assert(!io.stateDue(83) && io.stateDue(84));
  assert(!io.detailDue(983,false,false,true) && io.detailDue(984,false,false,true));
  C2Guard worst;
  strcpy(worst.session,"0123456789abcdef");
  worst.seq=worst.epoch=0xffffffffU; worst.reason="NETWORK_STARTUP_FAILED";
  worst.throttle=-255;
  char frame[512];
  int length=c2formatState(frame,sizeof(frame),worst,0xffffffffU,
    "4294967295,4294967295,4294967295,4294967295",
    "urc-r4-ffffffffffff","boot-ffffffff-ffffffff");
  assert(length>0 && length<512 && frame[length-1]=='}');
  assert(!c2formatState(frame,64,worst,1,"null,null,null,null","id","boot"));
  uint32_t oldAge=timingScenario(false), newAge=timingScenario(true);
  printf("Worst-width compact state: %d bytes. Synthetic ACK ages old/new: %lu/%lu ms.\n",
    length,(unsigned long)oldAge,(unsigned long)newAge);
  assert(oldAge>=350 && newAge<350);
  uint32_t sweepMax=0;
  for (uint32_t cost=30;cost<=55;++cost) {
    uint32_t age=timingScenario(true,cost);
    if (age>sweepMax) sweepMax=age;
    assert(age<350);
  }
  printf("Synthetic 30-55 ms compact-send sweep maximum ACK age: %lu ms.\n",(unsigned long)sweepMax);
  // A large idle reply may already be in progress when ARM is sent. Include
  // a full 110 ms transfer, 25 ms receive, and 55 ms urgent compact reply.
  C2Guard enableTiming;
  enableTiming.accept(command("HELLO",1,0),0);
  assert(enableTiming.accept(command("ARM",2,enableTiming.epoch),135));
  enableTiming.tick(190);
  assert(enableTiming.enabled && 190<250);
  char nonce[17];
  assert(c2discoveryQuery("C2DISC1,0123456789abcdef\n",25,nonce));
  assert(!strcmp(nonce,"0123456789abcdef"));
  assert(!c2discoveryQuery("C2DISC1,0123456789abcdeg",24,nonce));
  assert(!c2discoveryQuery("C2DISC1,0123456789abcdef,ARM",28,nonce));
  assert(!c2urgentReply(false,false,2,false,false,2,"DISARM"));
  assert(!c2urgentReply(false,true,3,false,true,3,"STOP"));
  assert(c2urgentReply(true,false,2,false,false,3,"DISARM"));
  for (const char* bad : {"", "MODE:TELEOP", "255,255", "C2V1,0123456789abcdef,0,1,ARM,0,0",
       "C2V1,0123456789abcdef,4294967296,1,ARM,0,0", "C2V1,0123456789abcdef,1,1,ARM,1,0",
       "C2V1,0123456789abcdef,1,1,DRIVE,128,128", "C2V1,0123456789abcdef,1,1,DRIVE,nan,0",
       "C2V1,0123456789abcdef,1,1,DRIVE,9999999999999999999999,0",
       "C2V1,0123456789abcdef,1,1,DRIVE,1.0,0", "C2V1,0123456789abcdef,1,1,ARM,0,0,extra"}) assert(!parse(bad));
  const char embeddedNul[]="C2V1\0,0123456789abcdef,1,1,ARM,0,0";
  assert(!parse(std::string(embeddedNul,sizeof(embeddedNul)-1)));
  assert(parse("C2V1,0123456789abcdef,1,1,DRIVE,-32,32\r\n"));
  assert(parse("C2V1,0123456789abcdef,1,1,DRIVE,128,0\n"));
  assert(parse("C2V1,0123456789abcdef,1,1,DRIVE,255,0\n"));
  assert(!parse("C2V1,0123456789abcdef,1,1,DRIVE,256,0\n"));
  C2Guard g;
  assert(!g.accept(command("ARM",1,1),0));
  assert(g.accept(command("HELLO",1,0),0));
  auto epoch=g.epoch;
  assert(!g.enabled);
  assert(g.accept(command("ARM",2,epoch),10));
  assert(g.enabled && !g.throttle);
  assert(g.accept(command("DRIVE",3,epoch,32,16),20));
  assert(g.throttle==32);
  assert(!g.accept(command("DRIVE",3,epoch,0,0),30));
  assert(g.accept(command("PING",4,epoch),250));
  g.tick(270); assert(!g.enabled && !g.throttle && g.epoch!=epoch);
  assert(!g.accept(command("DRIVE",5,epoch,32,0),271));
  assert(!g.accept(command("ARM",6,epoch),272));
  assert(g.accept(command("ARM",7,g.epoch),273));
  // Expiry is checked before an arriving DRIVE can revive motion.
  assert(!g.accept(command("DRIVE",8,g.epoch,32,0),523));
  assert(!g.enabled);
  assert(g.accept(command("STOP",9,g.epoch),524));
  assert(g.stopped);
  assert(!g.accept(command("ARM",10,g.epoch),525));
  assert(g.accept(command("RESET",11,g.epoch),526));
  assert(!g.stopped && !g.enabled);
  assert(g.accept(command("ARM",12,g.epoch),527));
  assert(g.accept(command("DISARM",13,g.epoch),528));
  assert(!g.enabled);
  auto other=command("HELLO",1,0); strcpy(other.session,"aaaaaaaaaaaaaaaa");
  assert(!g.accept(other,600));
  assert(g.accept(other,1528));
  assert(!g.accept(command("ARM",14,g.epoch),1529));
  C2Guard recovery;
  assert(recovery.accept(command("HELLO",1,0),0));
  assert(recovery.accept(command("ARM",2,recovery.epoch),1));
  auto oldDrive=command("DRIVE",3,recovery.epoch,30,0);
  recovery.networkLost();
  assert(!recovery.enabled && recovery.stopped && !*recovery.session);
  assert(!recovery.accept(oldDrive,2));
  assert(recovery.accept(command("HELLO",1,0),3));
  assert(!recovery.accept(command("ARM",2,recovery.epoch),4));
  assert(recovery.accept(command("RESET",3,recovery.epoch),5));
  assert(!recovery.enabled);
  assert(recovery.accept(command("ARM",4,recovery.epoch),6));
  C2Guard wrap;
  assert(wrap.accept(command("HELLO",1,0),0xffffff00U));
  assert(wrap.accept(command("ARM",2,wrap.epoch),0xffffff80U));
  wrap.tick(121); assert(wrap.enabled);
  wrap.tick(122); assert(!wrap.enabled);
  puts("C2Guard parser, ordering, watchdog, STOP, ownership and millis rollover checks passed.");
}
