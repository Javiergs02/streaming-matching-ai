import streamlit as st

def apply_portal_style():
    """
    Estilizado limpio para Streamlit:
    Oculta los enlaces molestos de anclaje en títulos y subtítulos al pasar el ratón.
    """
    st.markdown("""
    <style>
    /* Ocultar anclas automáticas en títulos y subtítulos */
    [data-testid="stHeaderActionElements"],
    [data-testid="stHeadingActionElements"],
    [data-testid="stHeadingWithActionElements"] a,
    .stHeadingActionElements,
    a.anchor-link,
    a.header-anchor,
    a[aria-label="Link to heading"],
    h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)
