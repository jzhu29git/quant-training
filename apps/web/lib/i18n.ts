export type PanelLocale = "en" | "zh-Hant";

type Messages = {
  brand: string;
  localeLabel: string;
  login: {
    title: string;
    subtitle: string;
    username: string;
    password: string;
    submit: string;
    error: string;
    accountHint: string;
  };
  shell: {
    signedInAs: string;
    logout: string;
    admin: string;
    viewer: string;
    nav: {
      overview: string;
      batch: string;
      data: string;
      models: string;
      picks: string;
      paper: string;
      admin: string;
    };
  };
  common: {
    yes: string;
    no: string;
    live: string;
    idle: string;
    checkNeeded: string;
    noRows: string;
    noLogs: string;
    lastStateUpdate: string;
    lastCode: string;
    remaining: string;
    logSource: string;
    rows: string;
    dateRange: string;
    latestDate: string;
    to: string;
    localStore: string;
  };
  overview: {
    title: string;
    subtitle: string;
    batchStatus: string;
    progress: string;
    dataFiles: string;
    topPicks: string;
    validationAuc: string;
    stateFileOnly: string;
    doneHint: string;
    latestDateHint: string;
    noInference: string;
    latestTraining: string;
    pulse: string;
    snapshot: string;
    stocksInUniverse: string;
    klineFiles: string;
    valuationFiles: string;
    latestInference: string;
    topSavedFeatures: string;
  };
  batch: {
    title: string;
    subtitle: string;
    running: string;
    done: string;
    failed: string;
    lastCode: string;
    savedLogLines: string;
    attemptedHint: string;
    remainingHint: string;
    noContainerMetadata: string;
    noStateTimestamp: string;
    noFileLog: string;
    state: string;
    topFailures: string;
    recentOutput: string;
    container: string;
    runningFor: string;
    window: string;
    currentPass: string;
    stateFile: string;
    to: string;
    reason: string;
    count: string;
    controls: string;
    readOnly: string;
    adminOnly: string;
    startAction: string;
    stopAction: string;
    runningHint: string;
    stoppedHint: string;
    noticeStarted: string;
    noticeStopped: string;
    errorForbidden: string;
    errorAlreadyRunning: string;
    errorNotRunning: string;
    errorNotFound: string;
    errorUnavailable: string;
    errorInvalidAction: string;
    errorControlFailed: string;
  };
  data: {
    title: string;
    subtitle: string;
    stocks: string;
    stocksHint: string;
    klineFiles: string;
    valuationFiles: string;
    storage: string;
    storageHint: string;
    sampleUniverse: string;
    klinePreview: string;
    valuationPreview: string;
    perStockFiles: string;
    quantDataSize: string;
  };
  models: {
    title: string;
    subtitle: string;
    auc: string;
    accuracy: string;
    trainRows: string;
    validRows: string;
    validationMetric: string;
    thresholdValidation: string;
    trainingSnapshot: string;
    backtestSnapshot: string;
    topFeatureImportance: string;
    features: string;
    categoricals: string;
    threshold: string;
    validationDays: string;
    totalReturn: string;
    cagr: string;
    maxDrawdown: string;
    rebalances: string;
    feature: string;
    importanceGain: string;
    importanceSplit: string;
  };
  picks: {
    title: string;
    subtitle: string;
    rows: string;
    latestDate: string;
    displayedPicks: string;
    rowsHint: string;
    latestSnapshot: string;
    topRankedRows: string;
    rankedSignals: string;
  };
  paper: {
    title: string;
    subtitle: string;
    daemon: string;
    gateway: string;
    latestSignal: string;
    lastSync: string;
    targetRows: string;
    openPositions: string;
    openOrders: string;
    totalPnl: string;
    controls: string;
    strategyTargets: string;
    livePositions: string;
    recentOrders: string;
    syncHistory: string;
    daemonLog: string;
    startAction: string;
    stopAction: string;
    controlHint: string;
    gatewayOffline: string;
    historyHint: string;
    targetsHint: string;
  };
};

const messages: Record<PanelLocale, Messages> = {
  en: {
    brand: "Aistock Control Panel",
    localeLabel: "English",
    login: {
      title: "Secure Login",
      subtitle: "Use your username and password to enter the quant dashboard. The interface language follows your account.",
      username: "Username",
      password: "Password",
      submit: "Enter Dashboard",
      error: "Invalid username or password.",
      accountHint: "admin uses English. guest will see Traditional Chinese after login."
    },
    shell: {
      signedInAs: "Signed in as",
      logout: "Logout",
      admin: "Admin",
      viewer: "Viewer",
      nav: {
        overview: "Overview",
        batch: "Pipeline",
        data: "Explorer",
        models: "Models",
        picks: "Picks",
        paper: "Paper",
        admin: "Admin"
      }
    },
    common: {
      yes: "Yes",
      no: "No",
      live: "Live",
      idle: "Idle",
      checkNeeded: "Check Needed",
      noRows: "No rows to display.",
      noLogs: "No log output available.",
      lastStateUpdate: "Last state update",
      lastCode: "Last code",
      remaining: "Remaining",
      logSource: "Log source",
      rows: "Rows",
      dateRange: "Date range",
      latestDate: "Latest date",
      to: "to",
      localStore: "local store"
    },
    overview: {
      title: "Quant Mission Control",
      subtitle: "A single place to monitor the batch, inspect the local A-share dataset, and review the latest model output without digging through shell scripts.",
      batchStatus: "Batch Status",
      progress: "Progress",
      dataFiles: "Data Files",
      topPicks: "Top Picks",
      validationAuc: "Validation AUC",
      stateFileOnly: "State file only",
      doneHint: "done",
      latestDateHint: "Latest date",
      noInference: "No inference snapshot",
      latestTraining: "Latest saved training metadata",
      pulse: "Live Batch Pulse",
      snapshot: "System Snapshot",
      stocksInUniverse: "Stocks in universe",
      klineFiles: "Kline files",
      valuationFiles: "Valuation files",
      latestInference: "Latest inference date",
      topSavedFeatures: "Top saved features"
    },
    batch: {
      title: "Batch Monitor",
      subtitle: "Track the long-running A-share downloader, verify that state is still moving, and inspect recent failure reasons without touching Docker by hand.",
      running: "Running",
      done: "Done",
      failed: "Failed",
      lastCode: "Last Code",
      savedLogLines: "Saved Log Lines",
      attemptedHint: "Attempted",
      remainingHint: "Remaining",
      noContainerMetadata: "No container metadata",
      noStateTimestamp: "No state timestamp",
      noFileLog: "No file log found",
      state: "Batch State",
      topFailures: "Top Failure Reasons",
      recentOutput: "Recent Live Output",
      container: "Container",
      runningFor: "Running for",
      window: "Window",
      currentPass: "Current pass index",
      stateFile: "State file",
      to: "to",
      reason: "Reason",
      count: "Count",
      controls: "Batch Controls",
      readOnly: "Read-only account",
      adminOnly: "Only admin accounts can start or stop the batch from the panel.",
      startAction: "Start Batch",
      stopAction: "Stop Batch",
      runningHint: "The downloader is currently live. Stop only if you want to interrupt the batch.",
      stoppedHint: "The downloader is idle. Start launches a fresh batch container with the current default settings.",
      noticeStarted: "Batch start request sent successfully.",
      noticeStopped: "Batch stop request sent successfully.",
      errorForbidden: "This account does not have permission to control the batch.",
      errorAlreadyRunning: "The batch is already running.",
      errorNotRunning: "The batch is not currently running.",
      errorNotFound: "No batch container record was found.",
      errorUnavailable: "Batch control is not configured correctly yet.",
      errorInvalidAction: "That control action is not valid.",
      errorControlFailed: "Batch control request failed. Check the API logs."
    },
    data: {
      title: "Data Explorer",
      subtitle: "Use this page to sanity-check what the machine actually downloaded. Pick a code, inspect date ranges, and look at real rows from both kline and valuation parquet files.",
      stocks: "Stocks",
      stocksHint: "Rows in stock_list.parquet",
      klineFiles: "Kline Files",
      valuationFiles: "Valuation Files",
      storage: "Storage",
      storageHint: "Current quant_data size",
      sampleUniverse: "Sample Stock Universe",
      klinePreview: "Kline Preview",
      valuationPreview: "Valuation Preview",
      perStockFiles: "Per-stock parquet files",
      quantDataSize: "Current quant_data size"
    },
    models: {
      title: "Model Center",
      subtitle: "Review the latest saved training metadata, inspect feature importance, and keep the backtest summary close to the training run that produced it.",
      auc: "AUC",
      accuracy: "Accuracy",
      trainRows: "Train Rows",
      validRows: "Valid Rows",
      validationMetric: "Validation metric",
      thresholdValidation: "Threshold-based validation",
      trainingSnapshot: "Training Snapshot",
      backtestSnapshot: "Backtest Snapshot",
      topFeatureImportance: "Top Feature Importance",
      features: "Features",
      categoricals: "Categoricals",
      threshold: "Threshold",
      validationDays: "Validation days",
      totalReturn: "Total return",
      cagr: "CAGR",
      maxDrawdown: "Max drawdown",
      rebalances: "Rebalances",
      feature: "Feature",
      importanceGain: "Importance Gain",
      importanceSplit: "Importance Split"
    },
    picks: {
      title: "Latest Picks",
      subtitle: "Inspect the most recent inference scores and surface the highest-ranked names without opening parquet files manually.",
      rows: "Rows",
      latestDate: "Latest Date",
      displayedPicks: "Displayed Picks",
      rowsHint: "Rows in inference_scores_latest.parquet",
      latestSnapshot: "Most recent scored snapshot",
      topRankedRows: "Top ranked rows",
      rankedSignals: "Ranked Signals"
    },
    paper: {
      title: "Auto Paper Trading",
      subtitle: "Connect the latest scored snapshot to your existing Futu gateway, track what the strategy wants to hold, and monitor the daemon that keeps the paper account in sync.",
      daemon: "Daemon",
      gateway: "Gateway",
      latestSignal: "Latest Signal",
      lastSync: "Last Sync",
      targetRows: "Target Rows",
      openPositions: "Open Positions",
      openOrders: "Open Orders",
      totalPnl: "Total PnL",
      controls: "Paper Controls",
      strategyTargets: "Strategy Targets",
      livePositions: "Live Positions",
      recentOrders: "Recent Orders",
      syncHistory: "Sync History",
      daemonLog: "Daemon Log",
      startAction: "Start Auto Trader",
      stopAction: "Stop Auto Trader",
      controlHint: "Start launches a long-running reconciler that watches new score snapshots and sends paper orders to the Futu gateway agent.",
      gatewayOffline: "Gateway is offline or unreachable right now. The panel is still showing the latest local strategy state.",
      historyHint: "Most recent rebalance attempts saved by the local strategy state.",
      targetsHint: "Latest desired portfolio generated from inference_scores_latest.parquet."
    }
  },
  "zh-Hant": {
    brand: "Aistock 量化控制台",
    localeLabel: "繁體中文",
    login: {
      title: "安全登入",
      subtitle: "請使用使用者名稱與密碼登入量化控制台。登入後介面語言會依帳號自動切換。",
      username: "使用者名稱",
      password: "密碼",
      submit: "進入控制台",
      error: "使用者名稱或密碼錯誤。",
      accountHint: "admin 會看到英文介面，guest 會看到繁體中文介面。"
    },
    shell: {
      signedInAs: "目前登入",
      logout: "登出",
      admin: "管理員",
      viewer: "只讀使用者",
      nav: {
        overview: "總覽",
        batch: "流程",
        data: "探索",
        models: "模型",
        picks: "選股",
        paper: "模擬",
        admin: "管理"
      }
    },
    common: {
      yes: "是",
      no: "否",
      live: "即時",
      idle: "待機",
      checkNeeded: "需檢查",
      noRows: "目前沒有可顯示的資料列。",
      noLogs: "目前沒有可顯示的日誌輸出。",
      lastStateUpdate: "狀態最後更新",
      lastCode: "最後代碼",
      remaining: "剩餘",
      logSource: "日誌來源",
      rows: "筆數",
      dateRange: "日期區間",
      latestDate: "最新日期",
      to: "到",
      localStore: "本地儲存"
    },
    overview: {
      title: "量化作業總控台",
      subtitle: "在同一個地方查看批次進度、檢查 A 股本地資料集，以及追蹤最新模型輸出，不必再翻 shell script。",
      batchStatus: "批次狀態",
      progress: "進度",
      dataFiles: "資料檔案",
      topPicks: "最新選股",
      validationAuc: "驗證 AUC",
      stateFileOnly: "僅有狀態檔",
      doneHint: "已完成",
      latestDateHint: "最新日期",
      noInference: "尚無推論快照",
      latestTraining: "最新儲存的訓練資訊",
      pulse: "批次即時脈動",
      snapshot: "系統快照",
      stocksInUniverse: "股票池總數",
      klineFiles: "K 線檔案數",
      valuationFiles: "估值檔案數",
      latestInference: "最新推論日期",
      topSavedFeatures: "已保存特徵數"
    },
    batch: {
      title: "批次監控",
      subtitle: "追蹤長時間執行的 A 股下載批次，確認狀態仍在前進，並查看最近的錯誤原因，不需要手動操作 Docker。",
      running: "是否執行中",
      done: "已完成",
      failed: "失敗",
      lastCode: "最後代碼",
      savedLogLines: "已保存日誌行數",
      attemptedHint: "已嘗試",
      remainingHint: "剩餘",
      noContainerMetadata: "沒有容器資訊",
      noStateTimestamp: "沒有狀態時間戳",
      noFileLog: "找不到落地日誌檔",
      state: "批次狀態",
      topFailures: "主要失敗原因",
      recentOutput: "最近即時輸出",
      container: "容器",
      runningFor: "已執行",
      window: "資料區間",
      currentPass: "目前輪次索引",
      stateFile: "狀態檔",
      to: "到",
      reason: "原因",
      count: "次數",
      controls: "批次控制",
      readOnly: "只讀帳號",
      adminOnly: "只有管理員帳號可以在面板中啟動或停止 batch。",
      startAction: "啟動 Batch",
      stopAction: "停止 Batch",
      runningHint: "下載批次目前正在執行中。只有在你確定要中斷工作時才停止。",
      stoppedHint: "下載批次目前未執行。啟動會用目前預設參數建立新的 batch 容器。",
      noticeStarted: "已成功送出 batch 啟動要求。",
      noticeStopped: "已成功送出 batch 停止要求。",
      errorForbidden: "這個帳號沒有控制 batch 的權限。",
      errorAlreadyRunning: "batch 已經在執行中了。",
      errorNotRunning: "batch 目前沒有在執行。",
      errorNotFound: "找不到 batch 容器紀錄。",
      errorUnavailable: "batch 控制功能目前尚未正確設定。",
      errorInvalidAction: "這個控制動作無效。",
      errorControlFailed: "batch 控制要求失敗，請查看 API 日誌。"
    },
    data: {
      title: "資料檢視",
      subtitle: "用這個頁面直接肉眼檢查系統實際下載了什麼。你可以挑一檔股票，查看日期範圍，以及 K 線與估值 parquet 的真實資料列。",
      stocks: "股票數",
      stocksHint: "stock_list.parquet 中的列數",
      klineFiles: "K 線檔案",
      valuationFiles: "估值檔案",
      storage: "儲存空間",
      storageHint: "目前 quant_data 大小",
      sampleUniverse: "股票池樣本",
      klinePreview: "K 線預覽",
      valuationPreview: "估值預覽",
      perStockFiles: "按股票拆分的 parquet 檔",
      quantDataSize: "目前 quant_data 大小"
    },
    models: {
      title: "模型中心",
      subtitle: "查看最新儲存的訓練資訊、檢查特徵重要性，並把回測摘要和產生它的訓練結果放在一起看。",
      auc: "AUC",
      accuracy: "準確率",
      trainRows: "訓練筆數",
      validRows: "驗證筆數",
      validationMetric: "驗證指標",
      thresholdValidation: "依門檻計算的驗證結果",
      trainingSnapshot: "訓練快照",
      backtestSnapshot: "回測快照",
      topFeatureImportance: "重要特徵排行",
      features: "特徵數",
      categoricals: "類別欄位",
      threshold: "門檻",
      validationDays: "驗證天數",
      totalReturn: "總報酬",
      cagr: "年化報酬率",
      maxDrawdown: "最大回撤",
      rebalances: "再平衡次數",
      feature: "特徵",
      importanceGain: "Gain 重要性",
      importanceSplit: "Split 重要性"
    },
    picks: {
      title: "最新選股",
      subtitle: "檢查最近一次推論分數，直接看到排名最高的股票，不必手動打開 parquet 檔。",
      rows: "資料列",
      latestDate: "最新日期",
      displayedPicks: "顯示中的選股",
      rowsHint: "inference_scores_latest.parquet 中的資料列",
      latestSnapshot: "最近一次已打分的快照",
      topRankedRows: "目前顯示的高分列",
      rankedSignals: "排序後訊號"
    },
    paper: {
      title: "自動模擬交易",
      subtitle: "把最新打分結果接到既有的 Futu gateway，查看策略想持有什麼，並監控持續同步模擬帳戶的 daemon。",
      daemon: "自動交易程序",
      gateway: "Gateway",
      latestSignal: "最新訊號日期",
      lastSync: "最後同步",
      targetRows: "目標列數",
      openPositions: "持倉數",
      openOrders: "委託數",
      totalPnl: "總損益",
      controls: "模擬交易控制",
      strategyTargets: "策略目標持倉",
      livePositions: "即時持倉",
      recentOrders: "最近委託",
      syncHistory: "同步歷史",
      daemonLog: "Daemon 日誌",
      startAction: "啟動自動交易",
      stopAction: "停止自動交易",
      controlHint: "啟動後會常駐監看新的 score snapshot，並把模擬委託送到 Futu gateway 的 agent。",
      gatewayOffline: "Gateway 目前離線或無法連線。面板仍會顯示最新的本地策略狀態。",
      historyHint: "本地策略狀態中保存的最近再平衡嘗試。",
      targetsHint: "由 inference_scores_latest.parquet 產生的最新目標投組。"
    }
  }
};

export function normalizeLocale(value?: string): PanelLocale {
  return value === "zh-Hant" ? "zh-Hant" : "en";
}

export function getMessages(locale: PanelLocale) {
  return messages[normalizeLocale(locale)];
}
