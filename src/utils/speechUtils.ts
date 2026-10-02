import { PlanStep } from '../types/nexus';

interface SpokenFormatOptions {
  spokenResponse?: string | null;
  finalResponse?: string | null;
  error?: string | null;
  goal?: string | null;
  prompt?: string | null;
  plan?: PlanStep[];
}

export function cleanSpokenError(error?: string | null): string {
  if (!error) return 'an unexpected issue occurred';
  const errLower = error.toLowerCase();
  if (errLower.includes('live dom') || errLower.includes('dom verification') || errLower.includes('missing required')) {
    return 'some required items were missing on the page';
  }
  if (errLower.includes('iteration limit') || errLower.includes('reached iteration')) {
    return 'the task reached the maximum step limit';
  }
  if (errLower.includes('not found') || errLower.includes('cannot locate') || errLower.includes('could not locate')) {
    return 'a required element could not be found on the screen';
  }
  if (errLower.includes('timed out') || errLower.includes('timeout')) {
    return 'the operation timed out';
  }
  if (errLower.includes('permission') || errLower.includes('denied')) {
    return 'permission was not granted';
  }
  if (errLower.includes('rate limit')) {
    return 'the service is temporarily rate limited';
  }
  if (errLower.includes('disconnected') || errLower.includes('offline')) {
    return 'the browser connection was interrupted';
  }

  // Strip code blocks, paths, backticks, urls, markdown
  const cleaned = error
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`]+`/g, '')
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
    .replace(/[A-Za-z]:\\[\w\s\\/.\-_]+/g, 'file')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/[#*_~|]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  const firstSentence = cleaned.split(/[.!?]\s+/)[0] || cleaned;
  if (firstSentence.length > 70) {
    return firstSentence.slice(0, 65).trim().toLowerCase() + '...';
  }
  return firstSentence.toLowerCase();
}

export function cleanSpokenSentence(text?: string | null, _maxChars?: number): string {
  if (!text) return '';
  const lines = text.split('\n');
  const validLines: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    // Drop table rows and table dividers
    if (line.startsWith('|') || line.endsWith('|') || /^[-:| ]+$/.test(line)) continue;
    // Drop markdown headers like ### Completed Successfully
    if (/^#{1,6}\s+/.test(line)) {
      const hdr = line.replace(/^#{1,6}\s+/, '').trim();
      const hdrLower = hdr.toLowerCase();
      if (
        hdrLower.includes('task completed') ||
        hdrLower.includes('completed successfully') ||
        hdrLower.includes('execution complete') ||
        hdrLower.includes('steps summary') ||
        hdrLower.includes('response') ||
        hdrLower.includes('findings') ||
        hdrLower.includes('task failed')
      ) {
        continue;
      }
      validLines.push(hdr);
      continue;
    }
    validLines.push(line);
  }

  let cleaned = validLines.join(' ')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/(?:^|\s)[-*+]\s+/g, ' ')
    .replace(/(?:^|\s)\d+\.\s+/g, ' ')
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
    .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
    .replace(/[✅❌⛔⚠️👉💡🔍📌🎉✨]|DOM Verification: Passed/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned) return '';

  // Extract first 1-2 clean complete sentences without cutting words
  const sentences = cleaned.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
  if (sentences.length > 0) {
    let candidate = sentences[0];
    if (candidate.length < 40 && sentences.length > 1) {
      candidate = `${candidate} ${sentences[1]}`;
    }
    if (!candidate.endsWith('.') && !candidate.endsWith('!') && !candidate.endsWith('?')) {
      candidate += '.';
    }
    return candidate;
  }

  return cleaned;
}

export function formatSpokenResponse({
  spokenResponse,
  finalResponse,
  error,
  goal,
  prompt,
  plan = [],
}: SpokenFormatOptions): string {
  // 1. If backend already generated a clean spokenResponse, use it directly (never chop)
  if (spokenResponse && spokenResponse.trim().length > 0) {
    return cleanSpokenSentence(spokenResponse) || spokenResponse.trim();
  }

  const context = `${goal || ''} ${prompt || ''}`.toLowerCase();
  const toolsUsed = plan.map(p => (p.tool || '').toLowerCase());

  const isExcel =
    context.includes('excel') ||
    context.includes('spreadsheet') ||
    context.includes('.xlsx') ||
    context.includes('csv') ||
    toolsUsed.some(t => t.includes('spreadsheet') || t.includes('excel'));

  const isWord =
    context.includes('word document') ||
    context.includes('document') ||
    context.includes('.docx') ||
    toolsUsed.some(t => t.includes('document'));

  const isFile =
    context.includes('create file') ||
    context.includes('write file') ||
    context.includes('save file') ||
    context.includes('script') ||
    toolsUsed.includes('write_file');

  const isEmail =
    context.includes('send email') ||
    context.includes('send mail') ||
    context.includes('compose email');

  const isForm =
    context.includes('google form') ||
    context.includes('create form') ||
    context.includes('fill form');

  // If there's an error
  if (error && !finalResponse) {
    const reason = cleanSpokenError(error);
    if (isExcel) return `I couldn't create the Excel file because ${reason}.`;
    if (isWord) return `I couldn't create the document because ${reason}.`;
    if (isEmail) return `I couldn't send the email because ${reason}.`;
    if (isForm) return `I couldn't complete the form because ${reason}.`;
    if (isFile) return `I couldn't save the file because ${reason}.`;
    return `I couldn't complete the task: ${reason}.`;
  }

  // Known high-value action responses
  if (isExcel) {
    if (context.includes('update') || context.includes('modify') || context.includes('add to')) {
      return 'I have updated the Excel file on your desktop.';
    }
    return 'I have successfully created the Excel file on your desktop.';
  }

  if (isWord) {
    if (context.includes('update') || context.includes('modify') || context.includes('add to')) {
      return 'I have updated the document on your desktop.';
    }
    return 'I have successfully created the document on your desktop.';
  }

  if (isEmail) {
    return 'I have sent the email for you.';
  }

  if (isForm) {
    if (context.includes('submit') || context.includes('fill')) {
      return 'I have filled and submitted the form for you.';
    }
    return 'I have successfully created the form for you.';
  }

  if (isFile) {
    return 'I have successfully saved the file to your desktop.';
  }

  // Extract from finalResponse (clean, complete sentence)
  if (finalResponse) {
    const sentence = cleanSpokenSentence(finalResponse);
    if (sentence && sentence.length > 10) {
      const lower = sentence.toLowerCase();
      if (
        !lower.startsWith('task completed') &&
        !lower.startsWith('execution complete') &&
        !lower.startsWith('here are the results')
      ) {
        return sentence;
      }
    }
  }

  return 'I have completed your task successfully.';
}
