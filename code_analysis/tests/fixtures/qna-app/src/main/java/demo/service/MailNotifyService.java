package demo.service;

@Service
public class MailNotifyService implements NotifyService {
    @Override
    public void send(String to) {
        System.out.println("mail " + to);
    }
}
