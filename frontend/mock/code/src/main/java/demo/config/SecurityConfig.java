package demo.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

// 가상 문의 앱 (mock). 실제 코드가 아니다.
@Configuration
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.authorizeHttpRequests(auth -> auth
                .requestMatchers("/login", "/signup", "/css/**", "/js/**").permitAll()
                .requestMatchers("/qna", "/qna/new").authenticated()
                .anyRequest().permitAll())
            .formLogin(form -> form
                .loginPage("/login")
                .usernameParameter("email")
                .defaultSuccessUrl("/qna")
                .failureUrl("/login?error"));
        return http.build();
    }
}
