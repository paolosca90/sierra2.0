// Universal Signal Trader v1.0 - Research REPLAY ONLY. Never routes live orders.
// Signals are extracted from subgraphs of ANY study with nonzero bullish/bearish values.
// WARNING: Requires a fresh, dedicated Sim# and Sierra Chart Trade Simulation Mode ON.
#include "sierrachart.h"
SCDLLName("Universal Signal Trader REPLAY SIM ONLY")
SCSFExport scsf_UniversalSignalTrader(SCStudyInterfaceRef sc)
{
    SCInputRef SourceStudy = sc.Input[0];
    SCInputRef UpSubgraph = sc.Input[1];
    SCInputRef DownSubgraph = sc.Input[2];
    SCInputRef ScoreSubgraph = sc.Input[3];
    SCInputRef Armed = sc.Input[4];
    SCInputRef Quantity = sc.Input[5];
    SCInputRef StopTicks = sc.Input[6];
    SCInputRef TargetTicks = sc.Input[7];
    SCInputRef MinimumScore = sc.Input[8];
    SCInputRef AllowLong = sc.Input[9];
    SCInputRef AllowShort = sc.Input[10];
    SCInputRef CloseOnOpposite = sc.Input[11];
    SCInputRef MaxHoldBars = sc.Input[12];
    if (sc.SetDefaults)
    {
        sc.GraphName = "Universal Signal Trader (REPLAY SIM ONLY)";
        sc.StudyDescription = "Generic study subgraph signals to simulated Sierra trades; no live trading possible. "
                              "Reads completed bars; brackets are optional, opposite signal or max bars can flatten.";
        sc.GraphRegion=0;
        sc.AutoLoop=0;
        sc.CalculationPrecedence=VERY_LOW_PREC_LEVEL;
        sc.UpdateAlways=1;
        sc.SendOrdersToTradeService=0;
        sc.MaintainTradeStatisticsAndTradesData=1;
        sc.AllowOnlyOneTradePerBar=1;
        sc.MaximumPositionAllowed=1;
        sc.AllowMultipleEntriesInSameDirection=0;
        sc.AllowOppositeEntryWithOpposingPositionOrOrders=0;
        sc.AllowEntryWithWorkingOrders=0;
        sc.SupportReversals=0;
        sc.SupportAttachedOrdersForTrading=1;
        sc.UseGUIAttachedOrderSetting=0;
        sc.CancelAllOrdersOnEntriesAndReversals=1;
        sc.Subgraph[0].Name="SIM Buy Request";
        sc.Subgraph[0].DrawStyle=DRAWSTYLE_ARROW_UP;
        sc.Subgraph[0].PrimaryColor=RGB(0,220,80);
        sc.Subgraph[0].DrawZeros=0;
        sc.Subgraph[1].Name="SIM Sell Request";
        sc.Subgraph[1].DrawStyle=DRAWSTYLE_ARROW_DOWN;
        sc.Subgraph[1].PrimaryColor=RGB(255,50,50);
        sc.Subgraph[1].DrawZeros=0;
        SourceStudy.Name="Signal Source Study ID";SourceStudy.SetStudyID(1);
        UpSubgraph.Name="LONG Signal Subgraph Index (0-based)";UpSubgraph.SetInt(10);UpSubgraph.SetIntLimits(0,59);
        DownSubgraph.Name="SHORT Signal Subgraph Index (0-based)";DownSubgraph.SetInt(11);DownSubgraph.SetIntLimits(0,59);
        ScoreSubgraph.Name="Signed Score Subgraph Index (-1 disables)";ScoreSubgraph.SetInt(9);ScoreSubgraph.SetIntLimits(-1,59);
        Armed.Name="ARM - REPLAY SIM ONLY (default OFF)";Armed.SetYesNo(0);
        Quantity.Name="Contracts";Quantity.SetInt(1);Quantity.SetIntLimits(1,1);
        StopTicks.Name="Stop Loss in ticks (0 disables; SIM ONLY)";StopTicks.SetInt(0);StopTicks.SetIntLimits(0,10000);
        TargetTicks.Name="Target in ticks (0 disables; SIM ONLY)";TargetTicks.SetInt(0);TargetTicks.SetIntLimits(0,10000);
        MinimumScore.Name="Minimum Absolute Signed Score";MinimumScore.SetFloat(0.30f);MinimumScore.SetFloatLimits(0.0f,10000.0f);
        AllowLong.Name="Allow LONG";AllowLong.SetYesNo(1);
        AllowShort.Name="Allow SHORT";AllowShort.SetYesNo(1);
        CloseOnOpposite.Name="Close Position On Opposite Signal";CloseOnOpposite.SetYesNo(1);
        MaxHoldBars.Name="Maximum Bars In Trade (0 disables)";MaxHoldBars.SetInt(60);MaxHoldBars.SetIntLimits(0,10000);
        return;
    }
    // Intentionally enforced on EVERY callback and not user-configurable.
    sc.SendOrdersToTradeService=0;
    sc.UseGUIAttachedOrderSetting=0;
    sc.AllowMultipleEntriesInSameDirection=0;
    sc.AllowOppositeEntryWithOpposingPositionOrOrders=0;
    sc.AllowEntryWithWorkingOrders=0;
    sc.SupportReversals=0;
    sc.MaximumPositionAllowed=1;
    int &primed=sc.GetPersistentInt(1);
    int &openAtBar=sc.GetPersistentInt(2);
    SCDateTime &lastClosedStart=sc.GetPersistentSCDateTime(1);
    if(sc.LastCallToFunction) return;
    if(sc.IsFullRecalculation){primed=0;openAtBar=-1;return;}
    if(!Armed.GetYesNo() || sc.GetReplayStatusFromChart(sc.ChartNumber)!=REPLAY_RUNNING ||
       !sc.GlobalTradeSimulationIsOn || sc.ArraySize<2 || sc.TickSize<=0)
    {primed=0;return;}
    const int closed=sc.ArraySize-2;
    const SCDateTime thisClosed=sc.BaseDateTimeIn[closed];
    if(!primed){primed=1;lastClosedStart=thisClosed;return;}
    if(thisClosed==lastClosedStart) return;
    if(thisClosed<lastClosedStart){lastClosedStart=thisClosed;openAtBar=-1;return;}
    lastClosedStart=thisClosed;
    const unsigned studyID=SourceStudy.GetStudyID();
    if(studyID==0 || studyID==(unsigned)sc.StudyGraphInstanceID) return;
    SCFloatArray up,down,score;
    if(sc.GetStudyArrayUsingID(studyID,UpSubgraph.GetInt(),up)<=0 ||
       sc.GetStudyArrayUsingID(studyID,DownSubgraph.GetInt(),down)<=0 ||
       up.GetArraySize()<=closed || down.GetArraySize()<=closed) return;
    const int scoreIdx=ScoreSubgraph.GetInt();
    if(scoreIdx>=0 && (sc.GetStudyArrayUsingID(studyID,scoreIdx,score)<=0 || score.GetArraySize()<=closed)) return;
    bool bull=AllowLong.GetYesNo() && up[closed]!=0.0f;
    bool bear=AllowShort.GetYesNo() && down[closed]!=0.0f;
    if(scoreIdx>=0){const float s=score[closed];
       if(bull && s<MinimumScore.GetFloat()) bull=false;
       if(bear && -s<MinimumScore.GetFloat()) bear=false;
    }
    s_SCPositionData pos;
    if(sc.GetTradePosition(pos)<=0) return;
    if(pos.PositionQuantity!=0){
        if(openAtBar<0) openAtBar = closed;
        const bool opposite=(pos.PositionQuantity>0 && bear) || (pos.PositionQuantity<0 && bull);
        const bool expired=MaxHoldBars.GetInt()>0 && openAtBar>=0 && (closed-openAtBar)>=MaxHoldBars.GetInt();
        if((CloseOnOpposite.GetYesNo() && opposite)||expired){
            int r=sc.FlattenAndCancelAllOrders();
            if(r<=0){SCString m; m.Format("Universal Signal Trader: flatten rejected %d",r);sc.AddMessageToLog(m,1);}
            else openAtBar=-1;
        }
        return;
    }
    openAtBar=-1;
    if(pos.WorkingOrdersExist || bull==bear) return;
    s_SCNewOrder order;
    order.OrderQuantity=Quantity.GetInt();
    order.OrderType=SCT_ORDERTYPE_MARKET;
    order.TimeInForce=SCT_TIF_GOOD_TILL_CANCELED;
    if(StopTicks.GetInt()>0)order.Stop1Offset=StopTicks.GetInt()*sc.TickSize;
    if(TargetTicks.GetInt()>0)order.Target1Offset=TargetTicks.GetInt()*sc.TickSize;
    order.TextTag="UNIVERSAL_REPLAY_SIM_V1";
    const int rc=bull?sc.BuyEntry(order,sc.ArraySize-1):sc.SellEntry(order,sc.ArraySize-1);
    if(rc>0){openAtBar=closed;
        if(bull) sc.Subgraph[0][sc.ArraySize-1]=sc.Low[sc.ArraySize-1]-sc.TickSize;
        else sc.Subgraph[1][sc.ArraySize-1]=sc.High[sc.ArraySize-1]+sc.TickSize;
    }else{SCString m;m.Format("Universal Signal Trader: entry rejected %d",rc);sc.AddMessageToLog(m,1);}
}
