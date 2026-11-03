// Read-only background service. Never enables trading or restarts a terminal.
#property service
#define FX_CALENDAR_SERVICE
#include "CalendarExport.mq5"

input int RefreshSeconds=60;
input int ExpectedBuild=0;
input datetime StopAtUTC=0;

void OnStart()
  {
   if(!SafeIdentity(ExportDirectory) || !SafeIdentity(BridgeId) ||
      RefreshSeconds<60 || RefreshSeconds>300 || ExpectedBuild<=0 ||
      TerminalInfoInteger(TERMINAL_BUILD)!=ExpectedBuild ||
      StopAtUTC<=TimeGMT() || StopAtUTC-TimeGMT()>31*86400 ||
      ExpectedServer=="" || AccountInfoString(ACCOUNT_SERVER)!=ExpectedServer ||
      !TerminalInfoInteger(TERMINAL_CONNECTED) ||
      AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
     { Print("Calendar service: configuration or connected demo check failed"); return; }
   string lock_name=ExportDirectory+"\\collector.lock";
   // No sharing flags: a second service instance cannot acquire this file.
   int lock=FileOpen(lock_name,FILE_WRITE|FILE_BIN);
   if(lock==INVALID_HANDLE)
     { Print("Calendar service: exclusive lock unavailable"); return; }
   long initial_login=AccountInfoInteger(ACCOUNT_LOGIN);
   datetime previous_utc=TimeGMT();
   ulong next=0;
   while(!IsStopped() && TimeGMT()<StopAtUTC &&
         !FileIsExist(ExportDirectory+"\\STOP"))
     {
      datetime now=TimeGMT();
      if(now<previous_utc || TerminalInfoInteger(TERMINAL_BUILD)!=ExpectedBuild)
        { Print("Calendar service: clock/build changed; stopped"); break; }
      previous_utc=now;
      if(TerminalInfoInteger(TERMINAL_CONNECTED) &&
         (AccountInfoInteger(ACCOUNT_LOGIN)!=initial_login ||
          AccountInfoString(ACCOUNT_SERVER)!=ExpectedServer ||
          AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO))
        { Print("Calendar service: account changed; stopped"); break; }
      if(GetTickCount64()>=next)
        {
         CaptureCalendar();
         next=GetTickCount64()+(ulong)RefreshSeconds*1000;
        }
      Sleep(250);
     }
   FileClose(lock);
   Print("Calendar service stopped; execution disabled");
  }
