// Read-only, one-shot calendar exporter. No trading, DLLs or external URLs.
#property strict
#property script_show_inputs
#property version "1.00"

input string BridgeId="fx_calendar_shadow";
input string ExpectedServer="";
input datetime ServerFrom=0;
input datetime ServerUntil=0;

bool WithinBudget(ulong start)
  {
   return !IsStopped() && GetTickCount64()-start<=30000;
  }

string Signed(long value) { return StringFormat("%I64d",value); }
string Unsigned(ulong value) { return StringFormat("%I64u",value); }

bool SafeIdentity(string value)
  {
   if(StringLen(value)<1 || StringLen(value)>64) return false;
   for(int i=0;i<StringLen(value);i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='a' && c<='z') || (c>='A' && c<='Z') ||
           (c>='0' && c<='9') || c=='_' || c=='-')) return false;
     }
   return true;
  }

void OnStart()
  {
   if(!SafeIdentity(BridgeId) || ServerFrom<=0 || ServerUntil<=ServerFrom ||
      ServerUntil-ServerFrom>31*86400)
     { Print("Calendar export: invalid explicit window or bridge ID"); return; }
   if(ExpectedServer=="" || AccountInfoString(ACCOUNT_SERVER)!=ExpectedServer ||
      !TerminalInfoInteger(TERMINAL_CONNECTED) ||
      AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
     { Print("Calendar export: connected demo terminal required"); return; }
   ulong start=GetTickCount64();
   long initial_login=AccountInfoInteger(ACCOUNT_LOGIN);
   datetime utc_start=TimeGMT();
   string currencies[3]={"USD","EUR","JPY"};
   string rows="";
   int counts[3]={0,0,0};
   int failure=0;
   int total=0;
   for(int c=0;c<3 && failure==0;c++)
     {
      if(!WithinBudget(start)) { failure=90001; break; }
      MqlCalendarValue values[500];
      ResetLastError();
      int count=CalendarValueHistory(values,ServerFrom,ServerUntil,NULL,currencies[c]);
      int error=GetLastError();
      if(count<0 || error!=0 || count>=500)
        { failure=(error!=0 ? error : 90002); break; }
      counts[c]=count;
      for(int i=0;i<count;i++)
        {
         if(!WithinBudget(start)) { failure=90001; break; }
         MqlCalendarEvent event;
         MqlCalendarCountry country;
         ResetLastError();
         if(!CalendarEventById(values[i].event_id,event))
           { failure=90003; break; }
         if(!WithinBudget(start)) { failure=90001; break; }
         if(!CalendarCountryById((long)event.country_id,country) ||
            country.currency!=currencies[c])
           { failure=90004; break; }
         if(total>0) rows+=",";
         rows+="{\"value_id\":\""+Unsigned(values[i].id)+"\",\"event_id\":\""+
            Unsigned(values[i].event_id)+"\",\"currency\":\""+currencies[c]+"\","+
            "\"server_time\":"+Signed((long)values[i].time)+","+
            "\"period_server_time\":"+Signed((long)values[i].period)+","+
            "\"source_revision\":"+IntegerToString(values[i].revision)+","+
            "\"time_mode\":\""+EnumToString(event.time_mode)+"\","+
            "\"importance\":\""+EnumToString(event.importance)+"\","+
            "\"unit\":\""+EnumToString(event.unit)+"\","+
            "\"multiplier\":\""+EnumToString(event.multiplier)+"\","+
            "\"digits\":"+IntegerToString((int)event.digits)+","+
            "\"actual_raw\":\""+Signed(values[i].actual_value)+"\","+
            "\"forecast_raw\":\""+Signed(values[i].forecast_value)+"\","+
            "\"previous_raw\":\""+Signed(values[i].prev_value)+"\","+
            "\"revised_previous_raw\":\""+Signed(values[i].revised_prev_value)+"\"}";
         total++;
         if(StringLen(rows)>1900000) { failure=90005; break; }
        }
     }
   if(!WithinBudget(start)) failure=90001;
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=initial_login ||
      AccountInfoString(ACCOUNT_SERVER)!=ExpectedServer ||
      !TerminalInfoInteger(TERMINAL_CONNECTED) ||
      AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO) failure=90006;
   datetime utc_end=TimeGMT();
   if(utc_end<utc_start) failure=90007;
   if(failure!=0) { rows=""; total=0; }
   string payload="{\"schema_version\":1,\"bridge_id\":\""+BridgeId+"\","+
      "\"terminal_build\":"+IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD))+","+
      "\"mode\":\"FULL_SNAPSHOT\",\"status\":\""+(failure==0 ? "COMPLETE" : "FAILED")+"\","+
      "\"error_code\":"+IntegerToString(failure)+","+
      "\"server_from\":"+Signed((long)ServerFrom)+",\"server_until\":"+Signed((long)ServerUntil)+","+
      "\"started_utc\":"+Signed((long)utc_start)+",\"finished_utc\":"+Signed((long)utc_end)+","+
      "\"elapsed_ms\":"+Unsigned(GetTickCount64()-start)+","+
      "\"counts\":{\"USD\":"+IntegerToString(counts[0])+",\"EUR\":"+IntegerToString(counts[1])+","+
      "\"JPY\":"+IntegerToString(counts[2])+"},\"values\":["+rows+"],\"execution_enabled\":false}";
   string name="fx-calendar-"+BridgeId+"-"+Signed((long)utc_start)+"-"+Unsigned(start);
   string temporary=name+".tmp";
   string destination=name+".json";
   if(FileIsExist(temporary) || FileIsExist(destination))
     { Print("Calendar export: existing artifact refused"); return; }
   int handle=FileOpen(temporary,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE) { Print("Calendar export: cannot create artifact"); return; }
   uint written=FileWriteString(handle,payload);
   FileFlush(handle);
   FileClose(handle);
   if(written!=(uint)StringLen(payload) || !FileMove(temporary,0,destination,0))
     { Print("Calendar export: incomplete artifact; temporary retained"); return; }
   Print("Calendar export saved: ",destination,"; execution disabled");
  }
