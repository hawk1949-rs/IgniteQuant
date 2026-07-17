import { useCallback, useEffect, useRef } from 'react'
import { motion, useMotionTemplate, useMotionValue } from 'motion/react'

import { cn } from '@/lib/utils'

interface MagicCardProps {
  children?: React.ReactNode
  className?: string
  gradientSize?: number
  gradientColor?: string
  gradientOpacity?: number
  gradientFrom?: string
  gradientTo?: string
}

export function MagicCard({
  children,
  className,
  gradientSize = 220,
  gradientColor = 'rgba(0, 113, 227, 0.08)',
  gradientOpacity = 1,
  gradientFrom = '#0071e3',
  gradientTo = '#86b7fe',
}: MagicCardProps) {
  const mouseX = useMotionValue(-gradientSize)
  const mouseY = useMotionValue(-gradientSize)
  const sizeRef = useRef(gradientSize)

  useEffect(() => {
    sizeRef.current = gradientSize
  }, [gradientSize])

  const reset = useCallback(() => {
    const off = -sizeRef.current
    mouseX.set(off)
    mouseY.set(off)
  }, [mouseX, mouseY])

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      mouseX.set(e.clientX - rect.left)
      mouseY.set(e.clientY - rect.top)
    },
    [mouseX, mouseY],
  )

  useEffect(() => {
    reset()
  }, [reset])

  const borderBg = useMotionTemplate`
    linear-gradient(#ffffff 0 0) padding-box,
    radial-gradient(${gradientSize}px circle at ${mouseX}px ${mouseY}px,
      ${gradientFrom},
      ${gradientTo},
      #d2d2d7 100%
    ) border-box
  `
  const spotBg = useMotionTemplate`
    radial-gradient(${gradientSize}px circle at ${mouseX}px ${mouseY}px,
      ${gradientColor},
      transparent 100%
    )
  `

  return (
    <motion.div
      className={cn(
        'group relative isolate overflow-hidden rounded-2xl border border-transparent',
        className,
      )}
      onPointerMove={handlePointerMove}
      onPointerLeave={reset}
      style={{ background: borderBg }}
    >
      <div className="absolute inset-px z-20 rounded-[inherit] bg-white/90 backdrop-blur-sm" />
      <motion.div
        className="pointer-events-none absolute inset-px z-30 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background: spotBg,
          opacity: gradientOpacity,
        }}
      />
      <div className="relative z-40">{children}</div>
    </motion.div>
  )
}
