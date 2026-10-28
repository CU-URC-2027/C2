# Prototype-only normalized drive inputs, NOT calibrated m/s or rad/s.
uint8 CLAIM=0
uint8 INPUT=1
uint8 ENABLE=2
uint8 DISARM=3
uint8 STOP=4
uint8 RESET=5
uint16 version
string session
string oc_boot
string challenge
uint64 sequence
uint64 epoch
uint8 operation
float64 throttle
float64 steering
bool deadman
