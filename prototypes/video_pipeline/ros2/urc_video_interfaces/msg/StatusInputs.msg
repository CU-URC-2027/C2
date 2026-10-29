# Aggregated inputs only. No allocation or encoder policy.
uint32 schema_version
uint64 output_sequence
bool priorities_received
bool bandwidth_received
bool inputs_ready
string[] ordered_stream_ids
uint32 enabled_count
string[] ranked_stream_ids
string[] omitted_stream_ids
# Ignore available_bandwidth_bps until bandwidth_received is true.
uint64 available_bandwidth_bps
string priority_session
uint64 priority_sequence
uint64 priority_revision
string bandwidth_session
uint64 bandwidth_sequence
# Age values are local monotonic receipt ages in seconds; -1 means missing.
float64 priority_age_s
float64 bandwidth_age_s
bool priorities_stale
bool bandwidth_stale
float64 stale_after_s
uint64 rejected_messages
