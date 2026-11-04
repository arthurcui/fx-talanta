#property strict
#property version "1.00"
#property description "Read-only bounded quote publisher. Contains no trading or network functions."

input long ExpectedLogin=0;
input string ExpectedServer="";
input string ExpectedSymbol="";
input string RunToken="";
input int MaxSeconds=600;
input int FlushMilliseconds=50;

struct Sample { MqlTick tick; ulong captured; datetime utc; string kind; };
Sample buffer[1024];
int head=0, count=0, output=INVALID_HANDLE;
ulong sequence=0, dropped=0, started=0, heartbeat=0;
bool stopping=false;
ulong tick_callbacks=0, read_errors=0;

bool SafeBinding() {
   return AccountInfoInteger(ACCOUNT_LOGIN)==ExpectedLogin &&
      AccountInfoString(ACCOUNT_SERVER)==ExpectedServer &&
      AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO &&
      !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && _Symbol==ExpectedSymbol;
}

void WriteSample(const Sample &sample) {
   sequence++;
   uint written=FileWrite(output,"quote-stream/1",RunToken,_Symbol,sample.kind,
      sequence,sample.tick.time_msc,DoubleToString(sample.tick.bid,_Digits),
      DoubleToString(sample.tick.ask,_Digits),sample.captured,GetTickCount64(),
      (long)sample.utc,dropped,(int)TerminalInfoInteger(TERMINAL_CONNECTED));
   if(written==0) { stopping=true; ExpertRemove(); }
}

void Drain() {
   ulong cutoff=GetTickCount64()+10;
   int remaining=256;
   while(count>0 && remaining-->0 && !stopping && GetTickCount64()<cutoff) {
      WriteSample(buffer[head]); head=(head+1)%1024; count--;
   }
   FileFlush(output);
}

void Capture(const string kind) {
   if(stopping) return;
   if(GetTickCount64()-started>=(ulong)MaxSeconds*1000) { ExpertRemove(); return; }
   if(!SafeBinding()) { stopping=true; ExpertRemove(); return; }
   if(count==1024) { dropped++; return; }
   Sample sample;
   sample.captured=GetTickCount64(); sample.utc=TimeGMT(); sample.kind=kind;
   if(!SymbolInfoTick(_Symbol,sample.tick)) { read_errors++; return; }
   buffer[(head+count)%1024]=sample; count++;
}

int OnInit() {
   EventKillTimer();
   if(output!=INVALID_HANDLE) FileClose(output);
   output=INVALID_HANDLE; head=0; count=0; sequence=0; dropped=0;
   started=0; heartbeat=0; stopping=false; tick_callbacks=0; read_errors=0;
   if(!SafeBinding() || ExpectedLogin<=0 || ExpectedServer=="" ||
      StringLen(RunToken)<8 || StringLen(RunToken)>64 ||
      MaxSeconds<10 || MaxSeconds>900 || FlushMilliseconds<20 || FlushMilliseconds>1000)
      return INIT_PARAMETERS_INCORRECT;
   for(int i=0;i<StringLen(RunToken);i++) {
      ushort c=StringGetCharacter(RunToken,i);
      if(!((c>='a' && c<='z') || (c>='0' && c<='9') || c=='-'))
         return INIT_PARAMETERS_INCORRECT;
   }
   string file_symbol=_Symbol;
   StringReplace(file_symbol,".","_");
   for(int i=0;i<StringLen(file_symbol);i++) {
      ushort c=StringGetCharacter(file_symbol,i);
      if(!((c>='a' && c<='z') || (c>='A' && c<='Z') ||
           (c>='0' && c<='9') || c=='_' || c=='-')) return INIT_PARAMETERS_INCORRECT;
   }
   string name="FXTalantaQuotes\\"+RunToken+"-"+file_symbol+".csv";
   if(FileIsExist(name,FILE_COMMON)) return INIT_FAILED;
   output=FileOpen(name,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',',CP_UTF8);
   if(output==INVALID_HANDLE) { Print("QUOTE_STREAM_FILE_OPEN_FAILED code=",GetLastError()); return INIT_FAILED; }
   started=GetTickCount64(); heartbeat=started;
   if(!EventSetMillisecondTimer(FlushMilliseconds)) { Print("QUOTE_STREAM_TIMER_FAILED code=",GetLastError()); FileClose(output); output=INVALID_HANDLE; return INIT_FAILED; }
   Capture("INITIAL");
   return INIT_SUCCEEDED;
}

void OnTick() { tick_callbacks++; Capture("TICK"); }

void OnTimer() {
   if(!SafeBinding() || GetTickCount64()-started>=(ulong)MaxSeconds*1000) {
      ExpertRemove(); return;
   }
   Drain();
   if(GetTickCount64()-heartbeat>=1000 && !stopping) {
      Sample sample; ZeroMemory(sample);
      sample.kind="HEARTBEAT"; sample.captured=GetTickCount64(); sample.utc=TimeGMT();
      WriteSample(sample); FileFlush(output); heartbeat=GetTickCount64();
   }
}

void OnDeinit(const int reason) {
   EventKillTimer();
   if(output!=INVALID_HANDLE) {
      // Cleanup must not drain an unbounded backlog. A single synchronous OS
      // write may still block: absence of this marker is incomplete evidence.
      bool incomplete=stopping || count>0;
      dropped+=(ulong)count; count=0;
      Sample sample; ZeroMemory(sample);
      sample.kind=incomplete ? "STOP_INCOMPLETE" : "STOP";
      sample.captured=GetTickCount64(); sample.utc=TimeGMT();
      Print("QUOTE_STREAM_DEINIT reason=",reason," unfinished=",incomplete,
         " tick_callbacks=",tick_callbacks," read_errors=",read_errors,
         " application_losses=",dropped," terminal_coalescing=UNMEASURED");
      WriteSample(sample); FileFlush(output); FileClose(output); output=INVALID_HANDLE;
   }
}
