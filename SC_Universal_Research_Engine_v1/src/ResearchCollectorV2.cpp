// Point-in-time closed-bar snapshots. No orders, no historical backfill.
#include "sierrachart.h"
#include <cstdio>
#include <cstring>
SCDLLName("Research Collector V2")

SCSFExport scsf_ResearchCollectorV2(SCStudyInterfaceRef sc)
{
    if (sc.SetDefaults)
    {
        sc.GraphName="Research Collector V2 (TO + causal Deluxe)";
        sc.AutoLoop=0;
        sc.UpdateAlways=1;
        sc.CalculationPrecedence=VERY_LOW_PREC_LEVEL;
        sc.GraphRegion=0;
        sc.Input[0].Name="TO Reversal Engine Study ID"; sc.Input[0].SetStudyID(1);
        sc.Input[1].Name="Causal TO Deluxe Study ID (0 disables)"; sc.Input[1].SetStudyID(0);
        sc.Input[2].Name="New CSV filename per replay"; sc.Input[2].SetString("TO_RESEARCH_V2_NQ.csv");
        sc.Input[3].Name="Enabled (replay only)"; sc.Input[3].SetYesNo(0);
        return;
    }
    int& primed=sc.GetPersistentInt(1);
    int& last=sc.GetPersistentInt(2);
    int& blocked=sc.GetPersistentInt(3);
    SCDateTime& lastStart=sc.GetPersistentSCDateTime(1);
    if (sc.LastCallToFunction) return;
    if (sc.IsFullRecalculation || sc.ReplayStatus==REPLAY_STOPPED || !sc.Input[3].GetYesNo())
    { primed=0; blocked=0; return; }
    if (sc.ReplayStatus!=REPLAY_RUNNING || sc.ArraySize<2 || blocked) return;
    const int source=sc.Input[0].GetStudyID(), levelsID=sc.Input[1].GetStudyID();
    int confirmations=-1, causal=0;
    SCString sourceName=sc.GetStudyNameUsingID(source);
    if (source<=0 || source==sc.StudyGraphInstanceID ||
        std::strstr(sourceName.GetChars(),"TO Reversal Engine")==nullptr ||
        !sc.GetChartStudyInputInt(sc.ChartNumber,source,10,confirmations) || confirmations!=0)
    {
        sc.AddMessageToLog("Collector V2 blocked: choose TO Reversal Engine with Confirmation Bars=0.",1);
        blocked=1; return;
    }
    if (levelsID)
    {
        SCString levelName=sc.GetStudyNameUsingID(levelsID);
        if (std::strstr(levelName.GetChars(),"TO Deluxe Levels")==nullptr ||
            !sc.GetChartStudyInputInt(sc.ChartNumber,levelsID,22,causal) || !causal)
        { sc.AddMessageToLog("Collector V2 blocked: Deluxe requires new Causal Research Mode=Yes.",1); blocked=1; return; }
    }
    const char* name=sc.Input[2].GetString();
    const size_t len=std::strlen(name);
    bool safe=len>4 && len<100 && std::strcmp(name+len-4,".csv")==0;
    for (size_t i=0;i<len;++i)
        safe=safe && ((name[i]>='a'&&name[i]<='z')||(name[i]>='A'&&name[i]<='Z')||
                      (name[i]>='0'&&name[i]<='9')||name[i]=='_'||name[i]=='-'||name[i]=='.');
    if (!safe) { sc.AddMessageToLog("Collector V2: invalid filename.",1); blocked=1; return; }
    SCString path=sc.DataFilesFolder(); path+="\\"; path+=name;
    const int current=sc.ArraySize-1;
    if (!primed)
    {
        FILE* existing=nullptr;
        if (fopen_s(&existing,path.GetChars(),"rb")==0 && existing)
        { std::fclose(existing); sc.AddMessageToLog("Collector V2: file exists. Choose a NEW name; never append replays.",1); blocked=1; return; }
        primed=1; last=current; lastStart=sc.BaseDateTimeIn[current]; return;
    }
    if (current<last || sc.BaseDateTimeIn[current]<lastStart)
    { sc.AddMessageToLog("Collector V2: rewind detected; new filename required.",1); blocked=1; return; }
    if (current==last) return;
    // Multiple bars closed between callbacks means historical snapshots would
    // all be observed late. Reject rather than silently use replay hindsight.
    if (current!=last+1)
    { sc.AddMessageToLog("Collector V2: skipped callbacks/bars. Reduce replay speed and restart with a new file.",1); blocked=1; return; }
    const int k=last;
    SCGraphData to, levels;
    sc.GetStudyArraysFromChartUsingID(sc.ChartNumber,source,to);
    if (levelsID) sc.GetStudyArraysFromChartUsingID(sc.ChartNumber,levelsID,levels);
    if (to.GetArraySize()<12 || (levelsID && levels.GetArraySize()<26))
    { sc.AddMessageToLog("Collector V2: source arrays missing.",1); blocked=1; return; }
    for (int i=0;i<12;++i) if (to[i].GetArraySize()<=k) { blocked=1; return; }
    for (int i=0;levelsID && i<26;++i) if (levels[i].GetArraySize()<=k) { blocked=1; return; }
    FILE* fp=nullptr;
    if (fopen_s(&fp,path.GetChars(),"ab+")!=0 || !fp)
    { sc.AddMessageToLog("Collector V2: cannot open CSV.",1); blocked=1; return; }
    std::fseek(fp,0,SEEK_END);
    if (std::ftell(fp)==0)
    {
        std::fputs("kind,run,symbol,observed_market_time,bar_index,bar_start,open,high,low,close,volume,signal_mask,reversal_score,levels_causal",fp);
        for(int i=0;i<26;++i) std::fprintf(fp,",level_%d",i);
        std::fputs("\n",fp);
    }
    const SCString observed=sc.DateTimeToString(sc.LatestDateTimeForLastBar,FLAG_DT_COMPLETE_DATETIME_MS);
    const SCString start=sc.DateTimeToString(sc.BaseDateTimeIn[k],FLAG_DT_COMPLETE_DATETIME_MS);
    const int mask=(to[10][k]!=0?1:0)|(to[11][k]!=0?2:0);
    std::fprintf(fp,"BAR_CLOSE,1,%s,%s,%d,%s,%.10g,%.10g,%.10g,%.10g,%.10g,%d,%.10g,%d",
        sc.Symbol.GetChars(),observed.GetChars(),k,start.GetChars(),sc.Open[k],sc.High[k],sc.Low[k],sc.Close[k],sc.Volume[k],mask,to[9][k],levelsID?1:0);
    for(int i=0;i<26;++i) std::fprintf(fp,",%.10g",levelsID?levels[i][k]:0.0);
    std::fputs("\n",fp);
    const bool error=std::ferror(fp)!=0;
    const int closeResult=std::fclose(fp);
    if(error || closeResult!=0) { sc.AddMessageToLog("Collector V2: write failed; discard incomplete run.",1); blocked=1; return; }
    last=current; lastStart=sc.BaseDateTimeIn[current];
}
