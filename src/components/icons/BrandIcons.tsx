import React from 'react';
import gmailSvg from '../../assets/connectors/gmail.svg';
import calendarSvg from '../../assets/connectors/calendar.svg';
import driveSvg from '../../assets/connectors/drive.svg';
import githubSvg from '../../assets/connectors/github.svg';
import spotifySvg from '../../assets/connectors/spotify.svg';
import slackSvg from '../../assets/connectors/slack.svg';
import notionSvg from '../../assets/connectors/notion.svg';
import linearSvg from '../../assets/connectors/linear.svg';
import todoistSvg from '../../assets/connectors/todoist.svg';

interface IconProps {
  className?: string;
}

export const GmailIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={gmailSvg} alt="Gmail" className={`${className} object-contain`} />
);

export const GoogleCalendarIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={calendarSvg} alt="Google Calendar" className={`${className} object-contain`} />
);

export const GoogleDriveIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={driveSvg} alt="Google Drive" className={`${className} object-contain`} />
);

export const GithubIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={githubSvg} alt="GitHub" className={`${className} object-contain`} />
);

export const SpotifyIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={spotifySvg} alt="Spotify" className={`${className} object-contain`} />
);

export const SlackIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={slackSvg} alt="Slack" className={`${className} object-contain`} />
);

export const NotionIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={notionSvg} alt="Notion" className={`${className} object-contain`} />
);

export const LinearIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={linearSvg} alt="Linear" className={`${className} object-contain`} />
);

export const TodoistIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <img src={todoistSvg} alt="Todoist" className={`${className} object-contain`} />
);

export const FilesystemIcon: React.FC<IconProps> = ({ className = 'w-5 h-5' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="2" y="5" width="20" height="15" rx="3" fill="#3B82F6" opacity="0.15" />
    <path
      d="M3 7C3 5.89543 3.89543 5 5 5H9.17157C9.70201 5 10.2107 5.21071 10.5858 5.58579L12 7H19C20.1046 7 21 7.89543 21 9V17C21 18.1046 20.1046 19 19 19H5C3.89543 19 3 18.1046 3 17V7Z"
      fill="#3B82F6"
    />
    <path
      d="M3 10H21V17C21 18.1046 20.1046 19 19 19H5C3.89543 19 3 18.1046 3 17V10Z"
      fill="#60A5FA"
    />
  </svg>
);
