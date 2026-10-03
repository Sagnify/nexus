import { contextBridge, ipcRenderer } from 'electron';

export interface ElectronAPI {
  hideWindow: () => void;
  showWindow: () => void;
  resizeWindow: (width: number, height: number, position?: 'center' | 'bottom') => void;
  showAutomationPill: () => void;
  hideAutomationPill: () => void;
  resizePill: (height: number) => void;
  syncTaskState: (state: any) => void;
  onTaskStateUpdate: (callback: (state: any) => void) => () => void;
  syncTeachState: (state: any) => void;
  onTeachStateUpdate: (callback: (state: any) => void) => () => void;
  sendPillAction: (action: string, payload?: any) => void;
  onPillAction: (callback: (data: { action: string; payload?: any }) => void) => () => void;
  quitApp: () => void;
  onWindowBlur: (callback: () => void) => () => void;
  onWindowShow: (callback: () => void) => () => void;
  onWindowHide: (callback: () => void) => () => void;
  onScheduledEmailBrief?: (callback: (target: { taskId: string; runId: string }) => void) => () => void;
  wakeSpotlight: () => void;
  onRemoteTeachFinished?: (callback: () => void) => () => void;
  onVoiceStartCapture: (callback: () => void) => () => void;
  getFileIcon: (filePath: string) => Promise<string | null>;
  selectSavePath: (defaultFilename?: string) => Promise<string | null>;
  selectFolder: () => Promise<string | null>;
  showInFolder: (filePath: string) => Promise<boolean>;
  openPath: (filePath: string) => Promise<string>;
  openExternal: (url: string) => void;
  resizeExcelCopilot?: (hwnd: number, width: number, height: number) => void;
  platform: string;
}

const api: ElectronAPI = {
  getFileIcon: (filePath: string) => ipcRenderer.invoke('get-file-icon', filePath),
  selectSavePath: (defaultFilename?: string) => ipcRenderer.invoke('select-save-path', defaultFilename),
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  showInFolder: (filePath: string) => ipcRenderer.invoke('show-in-folder', filePath),
  openPath: (filePath: string) => ipcRenderer.invoke('open-path', filePath),
  openExternal: (url: string) => ipcRenderer.send('open-external', url),
  hideWindow: () => ipcRenderer.send('window-hide'),
  showWindow: () => ipcRenderer.send('window-show'),
  wakeSpotlight: () => ipcRenderer.send('spotlight-wake'),

  onRemoteTeachFinished: (callback: () => void) => {
    const handler = () => callback();
    ipcRenderer.on('remote-teach-finished', handler);
    return () => {
      ipcRenderer.removeListener('remote-teach-finished', handler);
    };
  },
  onVoiceStartCapture: (callback: () => void) => {
    const handler = () => callback();
    ipcRenderer.on('voice-start-capture', handler);
    return () => {
      ipcRenderer.removeListener('voice-start-capture', handler);
    };
  },
  resizeWindow: (width: number, height: number, position?: 'center' | 'bottom') =>
    ipcRenderer.send('window-resize', { width, height, position }),
  showAutomationPill: () => ipcRenderer.send('show-automation-pill'),
  hideAutomationPill: () => ipcRenderer.send('hide-automation-pill'),
  resizePill: (height: number) => ipcRenderer.send('pill-resize', { height }),
  syncTaskState: (state: any) => ipcRenderer.send('sync-task-state', state),
  onTaskStateUpdate: (callback: (state: any) => void) => {
    const handler = (_event: any, state: any) => callback(state);
    ipcRenderer.on('task-state-updated', handler);
    return () => {
      ipcRenderer.removeListener('task-state-updated', handler);
    };
  },
  syncTeachState: (state: any) => ipcRenderer.send('sync-teach-state', state),
  onTeachStateUpdate: (callback: (state: any) => void) => {
    const handler = (_event: any, state: any) => callback(state);
    ipcRenderer.on('teach-state-updated', handler);
    return () => {
      ipcRenderer.removeListener('teach-state-updated', handler);
    };
  },
  sendPillAction: (action: string, payload?: any) =>
    ipcRenderer.send('pill-action', { action, payload }),
  onPillAction: (callback: (data: { action: string; payload?: any }) => void) => {
    const handler = (_event: any, data: { action: string; payload?: any }) => callback(data);
    ipcRenderer.on('pill-action-received', handler);
    return () => {
      ipcRenderer.removeListener('pill-action-received', handler);
    };
  },
  quitApp: () => ipcRenderer.send('app-quit'),
  onWindowBlur: (callback: () => void) => {
    const handler = () => callback();
    ipcRenderer.on('window-blurred', handler);
    return () => {
      ipcRenderer.removeListener('window-blurred', handler);
    };
  },
  onWindowShow: (callback: () => void) => {
    const handler = () => callback();
    ipcRenderer.on('window-shown', handler);
    return () => {
      ipcRenderer.removeListener('window-shown', handler);
    };
  },
  onWindowHide: (callback: () => void) => {
    const handler = () => callback();
    ipcRenderer.on('window-hidden', handler);
    return () => {
      ipcRenderer.removeListener('window-hidden', handler);
    };
  },
  onScheduledEmailBrief: (callback: (target: { taskId: string; runId: string }) => void) => {
    const handler = (_event: any, target: { taskId: string; runId: string }) => callback(target);
    ipcRenderer.on('open-scheduled-email-brief', handler);
    return () => ipcRenderer.removeListener('open-scheduled-email-brief', handler);
  },
  resizeExcelCopilot: (hwnd: number, width: number, height: number) =>
    ipcRenderer.send('excel-copilot-resize', { hwnd, width, height }),
  platform: process.platform,
};

contextBridge.exposeInMainWorld('electronAPI', api);
