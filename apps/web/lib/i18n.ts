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
    signalDate: string;
    sourceCloseDate: string;
    rawSyncDate: string;
    featureTime: string;
    modelTime: string;
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

const messages: Messages = {
  brand: "Aistock Control Panel",
  localeLabel: "English",
  login: {
    title: "Secure Login",
    subtitle: "Use your username and password to enter the quant dashboard.",
    username: "Username",
    password: "Password",
    submit: "Enter Dashboard",
    error: "Invalid username or password.",
    accountHint: "Replace the sample users and password hashes before exposing the panel to anyone else."
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
    signalDate: "Signal Date",
    sourceCloseDate: "Source Close Date",
    rawSyncDate: "Raw Sync Date",
    featureTime: "Feature Time",
    modelTime: "Model Time",
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
};

export function normalizeLocale(_value?: string): PanelLocale {
  return "en";
}

export function getMessages(_locale: PanelLocale) {
  return messages;
}
