#property strict
#property tester_file "m2b-requests.tsv"
#include "NativeTests.mqh"
int OnInit(){ if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED; return FxRunNativeTests() ? INIT_SUCCEEDED : INIT_FAILED; }
void OnTick(){}
double OnTester(){ return fx_failures==0 ? fx_checks : -fx_failures; }
