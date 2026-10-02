import React, { useState } from 'react';
import defaultLogo from '../assets/nexus-logo.png';

export interface NexusLogoMediaProps {
  type?: 'video' | 'image';
  videoSrc?: string;
  imageSrc?: string;
  className?: string;
  mediaClassName?: string;
  alt?: string;
  skeletonClassName?: string;
  title?: string;
  onClick?: () => void;
}

export const NexusLogoMedia: React.FC<NexusLogoMediaProps> = ({
  type = 'video',
  videoSrc = '/nexus_loader.webm',
  imageSrc = defaultLogo,
  className = 'w-7 h-7',
  mediaClassName = '',
  alt = 'NEXUS',
  skeletonClassName = '',
  title,
  onClick,
}) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasError, setHasError] = useState(false);

  return (
    <div
      className={`relative flex items-center justify-center overflow-hidden shrink-0 select-none ${className}`}
      title={title}
      onClick={onClick}
    >
      {/* SKELETON LOADER (Glowing cybernetic pulse until loaded) */}
      {!isLoaded && (
        <div
          className={`absolute inset-0 flex items-center justify-center rounded-full pointer-events-none z-0 transition-opacity duration-300 ${skeletonClassName}`}
          style={{
            background: 'radial-gradient(circle at 50% 50%, rgba(56, 189, 248, 0.22), rgba(168, 85, 247, 0.15) 50%, rgba(15, 23, 42, 0.7) 100%)',
            boxShadow: 'inset 0 0 10px rgba(56, 189, 248, 0.3)',
          }}
        >
          {/* Subtle animated orbital shimmer ring */}
          <div
            className="absolute inset-0 rounded-full border border-cyan-400/30 animate-ping opacity-35"
            style={{ animationDuration: '2.2s' }}
          />
          {/* Glowing central micro-orb */}
          <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(56,189,248,0.95)] animate-pulse" />
        </div>
      )}

      {/* VIDEO LOGO */}
      {type === 'video' && !hasError && (
        <video
          src={videoSrc}
          autoPlay
          loop
          muted
          playsInline
          onLoadedData={() => setIsLoaded(true)}
          onCanPlay={() => setIsLoaded(true)}
          onPlaying={() => setIsLoaded(true)}
          onError={() => setHasError(true)}
          className={`w-full h-full object-cover pointer-events-none transition-opacity duration-300 ${
            isLoaded ? 'opacity-100' : 'opacity-0'
          } ${mediaClassName}`}
        />
      )}

      {/* IMAGE LOGO */}
      {(type === 'image' || hasError) && (
        <img
          src={hasError ? defaultLogo : imageSrc}
          alt={alt}
          onLoad={() => setIsLoaded(true)}
          onError={() => setIsLoaded(true)}
          className={`w-full h-full object-contain pointer-events-none transition-opacity duration-300 ${
            isLoaded ? 'opacity-100' : 'opacity-0'
          } ${mediaClassName}`}
        />
      )}
    </div>
  );
};

export default NexusLogoMedia;
