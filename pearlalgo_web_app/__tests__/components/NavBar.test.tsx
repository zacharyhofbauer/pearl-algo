import React from 'react'
import { render, screen } from '@testing-library/react'
import NavBar from '@/components/NavBar'

const mockUsePathname = jest.fn()
jest.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
}))

jest.mock('next/image', () => ({
  __esModule: true,
  default: ({ src, alt }: { src: string; alt: string }) => (
    <img src={src} alt={alt} data-testid="nav-logo" />
  ),
}))

describe('NavBar', () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue('/')
  })

  it('renders brand link to home', () => {
    render(<NavBar />)
    const brand = screen.getByRole('link', { name: /PEARL Home/i })
    expect(brand).toHaveAttribute('href', '/')
  })

  it('renders Dashboard link with tv_paper account', () => {
    render(<NavBar />)
    const dashboard = screen.getByRole('link', { name: /Dashboard/i })
    expect(dashboard).toHaveAttribute('href', '/dashboard?account=tv_paper')
  })

  it('renders Archive link to ibkr', () => {
    render(<NavBar />)
    const archive = screen.getByRole('link', { name: /Archive/i })
    expect(archive).toHaveAttribute('href', '/archive/ibkr')
  })

  it('highlights brand as active when on landing', () => {
    mockUsePathname.mockReturnValue('/')
    render(<NavBar />)
    const brand = screen.getByRole('link', { name: /PEARL Home/i })
    expect(brand).toHaveClass('active')
    expect(brand).toHaveAttribute('aria-current', 'page')
  })

  it('highlights Dashboard when on /dashboard', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<NavBar />)
    const dashboard = screen.getByRole('link', { name: /Dashboard/i })
    expect(dashboard).toHaveClass('active')
    expect(dashboard).toHaveAttribute('aria-current', 'page')
  })

  it('highlights Archive when on /archive', () => {
    mockUsePathname.mockReturnValue('/archive/ibkr')
    render(<NavBar />)
    const archive = screen.getByRole('link', { name: /Archive/i })
    expect(archive).toHaveClass('active')
    expect(archive).toHaveAttribute('aria-current', 'page')
  })

  it('has navigation role and aria-label', () => {
    render(<NavBar />)
    const nav = screen.getByRole('navigation', { name: /Main/i })
    expect(nav).toBeInTheDocument()
  })
})
