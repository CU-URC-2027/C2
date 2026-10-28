#pragma once
// Local credentials are intentionally excluded from Git.
#if __has_include("wifi_credentials.local.h")
#include "wifi_credentials.local.h"
#else
#define C2_WIFI_SSID "YOUR_ROUTER_SSID"
#define C2_WIFI_PASSWORD "YOUR_ROUTER_PASSWORD"
#endif
