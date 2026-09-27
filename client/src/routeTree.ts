import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { RootLayout } from './routes/__root'
import { IndexPage } from './routes/landing'
import { LoginPage, SignupPage } from './routes/auth'
import { PricingPage, SuccessPage } from './routes/pricing'

const rootRoute = createRootRoute({ component: RootLayout })
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: IndexPage })
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: '/login', component: LoginPage })
const signupRoute = createRoute({ getParentRoute: () => rootRoute, path: '/signup', component: SignupPage })
const pricingRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pricing', component: PricingPage })
const successRoute = createRoute({ getParentRoute: () => rootRoute, path: '/success', component: SuccessPage })
const routeTree = rootRoute.addChildren([indexRoute, loginRoute, signupRoute, pricingRoute, successRoute])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
