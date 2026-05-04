import { Layout, Nav } from '@douyinfe/semi-ui'
import { IconHome, IconFolder } from '@douyinfe/semi-icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'

const { Sider, Content } = Layout

export default function AppLayout() {
    const navigate = useNavigate()
    const location = useLocation()

    const navItems = [
        { itemKey: '/', text: 'Home', icon: <IconHome /> },
        { itemKey: '/projects', text: 'Projects', icon: <IconFolder /> },
    ]

    const selectedKey = location.pathname === '/' ? '/' : `/${location.pathname.split('/')[1]}`

    return (
        <Layout style={{ minHeight: '100vh' }}>
            <Sider style={{ backgroundColor: 'var(--semi-color-bg-1)' }}>
                <Nav
                    items={navItems}
                    selectedKeys={[selectedKey]}
                    onClick={({ itemKey }) => navigate(itemKey as string)}
                    style={{ height: '100%' }}
                    header={{
                        text: 'MangaForge',
                    }}
                />
            </Sider>
            <Content style={{ padding: '24px', backgroundColor: 'var(--semi-color-bg-0)' }}>
                <Outlet />
            </Content>
        </Layout>
    )
}
